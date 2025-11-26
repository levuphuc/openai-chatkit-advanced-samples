"""
Universal Web Crawler - Crawl bất kỳ website nào với chiến lược tự động
Hỗ trợ:
- Static sites (server-side rendering)
- React/Vue/Angular SPA (client-side rendering)
- Hybrid sites
- Auto-detect và fallback strategies
"""

import asyncio, os, re, hashlib, json
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
)

class CrawlStrategy:
    """Enum cho các chiến lược crawl"""
    DIRECT = "direct"  # Truy cập trực tiếp URL
    SPA_WITH_DELAY = "spa_with_delay"  # SPA với delay để JS render
    NAVIGATE_FROM_HOME = "navigate_from_home"  # Navigate từ trang chủ

class CrawlResult:
    """Kết quả crawl một trang"""
    def __init__(self, url, success=False, strategy=None):
        self.url = url
        self.success = success
        self.strategy = strategy
        self.title = ""
        self.content = ""
        self.description = ""
        self.html_size = 0
        self.cleaned_text_size = 0
        self.is_404 = False
        
class UniversalCrawler:
    """Crawler tổng quát cho mọi loại website"""
    
    def __init__(self, base_url, output_dir="crawled_data", config=None):
        self.base_url = base_url.rstrip('/')
        self.domain = urlparse(base_url).netloc
        self.output_dir = output_dir
        self.config = config or {}
        
        # Cấu hình ngưỡng
        self.min_content_length = self.config.get('min_content_length', 200)
        self.min_cleaned_ratio = self.config.get('min_cleaned_ratio', 0.1)  # 10% của HTML
        
        os.makedirs(output_dir, exist_ok=True)
        
    def slugify(self, text: str) -> str:
        """Chuyển text thành slug an toàn cho tên file (giữ nguyên nguyên âm tiếng Việt thành ASCII).

        Cải tiến: dùng Unicode decomposition để loại bỏ dấu mà KHÔNG mất nguyên âm.
        Khắc phục lỗi trước đây tạo slug như "lin-h-vi-chng-ti" thay vì "lien-he-voi-chung-toi".
        """
        import unicodedata
        if not text:
            return "page"
        # Chuẩn hoá & tách tổ hợp
        text_norm = unicodedata.normalize("NFD", text)
        out_chars = []
        for ch in text_norm:
            # Bỏ các dấu (combining marks)
            if unicodedata.category(ch) == "Mn":
                continue
            # Chuyển đ/Đ
            if ch == "đ":
                ch = "d"
            elif ch == "Đ":
                ch = "D"
            out_chars.append(ch)
        ascii_text = "".join(out_chars)
        ascii_text = unicodedata.normalize("NFC", ascii_text).lower()
        # Giữ lại chữ cái, số, khoảng trắng và dấu '-'
        ascii_text = re.sub(r"[^a-z0-9\s-]", "", ascii_text)
        # Thu gọn khoảng trắng -> '-'
        ascii_text = re.sub(r"\s+", "-", ascii_text.strip())
        # Thu gọn nhiều dấu '-' liên tiếp
        ascii_text = re.sub(r"-+", "-", ascii_text)
        return ascii_text[:80] or "page"
    
    def url_hash(self, url: str) -> str:
        """Tạo hash 8 ký tự từ URL"""
        return hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    
    def extract_content(self, result, soup=None) -> dict:
        """Trích xuất nội dung từ kết quả crawl"""
        if soup is None:
            html = result.html or ""
            soup = BeautifulSoup(html, "html.parser")
        
        # Lấy tiêu đề
        title = ""
        h1_tags = soup.find_all("h1")
        if h1_tags:
            for h1 in h1_tags:
                text = h1.get_text(strip=True)
                # Bỏ qua h1 là logo/site name
                if text and len(text) > 3 and text.lower() not in [self.domain.lower()]:
                    title = text
                    break
            if not title and h1_tags:
                title = h1_tags[0].get_text(strip=True)
        
        # Fallback từ metadata
        if not title and result.metadata:
            meta = result.metadata
            title = meta.get("title") or meta.get("og:title") or ""
            
        if not title:
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
                
        # Lấy nội dung chính
        content = ""
        
        # Thử các selector phổ biến
        main_selectors = [
            "main", "article", "[role='main']",
            ".main-content", ".content", "#content",
            ".post-content", ".entry-content",
            ".article-content", ".page-content"
        ]
        
        for selector in main_selectors:
            main_tag = soup.select_one(selector)
            if main_tag:
                content = main_tag.get_text("\n", strip=True)
                if len(content) > 100:
                    break
        
        # Fallback: từ body (loại bỏ header/footer/nav)
        if not content or len(content) < 100:
            body = soup.find("body")
            if body:
                body_copy = BeautifulSoup(str(body), "html.parser")
                for tag in body_copy.find_all(["header", "footer", "nav", "aside"]):
                    tag.decompose()
                content = body_copy.get_text("\n", strip=True)
        
        # Description
        description = ""
        if result.metadata:
            description = result.metadata.get("description") or result.metadata.get("og:description") or ""
        
        # Kiểm tra 404
        page_text = soup.get_text().lower()
        is_404 = any([
            "page not found" in page_text,
            "404" in title.lower(),
            "not found" in title.lower() and len(content) < 500
        ])
        
        return {
            "title": title or "Không có tiêu đề",
            "content": content,
            "description": description,
            "is_404": is_404,
            "html_size": len(result.html or ""),
            "cleaned_text_size": len(content)
        }
    
    def evaluate_content_quality(self, extracted_data) -> bool:
        """Đánh giá chất lượng nội dung đã crawl"""
        # 1) Loại trừ trang 404
        if extracted_data["is_404"]:
            return False

        text_len = extracted_data["cleaned_text_size"]
        html_size = extracted_data["html_size"] or 0
        ratio = (text_len / html_size) if html_size else 1.0

        # 2) Độ dài tối thiểu tuyệt đối
        if text_len < self.min_content_length:
            return False

        # 3) Chiến lược đánh giá linh hoạt theo ratio:
        #    - Nếu nội dung đủ dài (> 2 * min_content_length) thì bỏ qua ratio (trang nhiều markup như SPA)
        #    - Nếu ratio dưới ngưỡng nhưng vẫn > ngưỡng nới lỏng (half) và text đủ dài thì chấp nhận.
        #    - Ngưỡng tối thiểu tuyệt đối cho ratio là 0.02 (tránh nhận trang hầu như toàn script).
        if ratio < self.min_cleaned_ratio:
            relaxed_threshold = max(0.02, self.min_cleaned_ratio / 2)
            if text_len >= self.min_content_length * 2:
                return True  # đủ dài, chấp nhận
            if ratio >= relaxed_threshold and text_len >= int(self.min_content_length * 1.2):
                return True  # nới lỏng
            return False

        return True
    
    async def crawl_with_strategy(self, crawler, url: str, strategy: str, base_config: CrawlerRunConfig) -> CrawlResult:
        """Crawl với một chiến lược cụ thể"""
        result = CrawlResult(url, strategy=strategy)
        
        try:
            if strategy == CrawlStrategy.DIRECT:
                # Crawl trực tiếp, không delay
                config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    word_count_threshold=0,
                    verbose=False,
                    page_timeout=30000,
                    delay_before_return_html=1.0,
                )
                crawl_result = await crawler.arun(url=url, config=config)
                
            elif strategy == CrawlStrategy.SPA_WITH_DELAY:
                # SPA với delay dài hơn
                config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    word_count_threshold=0,
                    verbose=False,
                    page_timeout=60000,
                    delay_before_return_html=5.0,
                )
                crawl_result = await crawler.arun(url=url, config=config)
                
            elif strategy == CrawlStrategy.NAVIGATE_FROM_HOME:
                # Navigate từ trang chủ
                if url == self.base_url:
                    # Nếu đang ở trang chủ, dùng SPA_WITH_DELAY
                    return await self.crawl_with_strategy(crawler, url, CrawlStrategy.SPA_WITH_DELAY, base_config)
                
                # Tạo JS code để navigate
                path = url.replace(self.base_url, '').lstrip('/')
                js_click_code = f"""
                // Đợi trang load
                await new Promise(resolve => setTimeout(resolve, 2000));
                
                // Tìm link và click
                const links = Array.from(document.querySelectorAll('a[href*="/{path}"]'));
                if (links.length > 0) {{
                    links[0].click();
                    await new Promise(resolve => setTimeout(resolve, 3000));
                }} else {{
                    // Thử tìm link với path đầy đủ
                    const fullLinks = Array.from(document.querySelectorAll('a[href="{url}"]'));
                    if (fullLinks.length > 0) {{
                        fullLinks[0].click();
                        await new Promise(resolve => setTimeout(resolve, 3000));
                    }}
                }}
                """
                
                config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    word_count_threshold=0,
                    verbose=False,
                    page_timeout=60000,
                    delay_before_return_html=5.0,
                    js_code=js_click_code,
                )
                
                # Load trang chủ với JS click
                crawl_result = await crawler.arun(url=self.base_url, config=config)
            
            else:
                raise ValueError(f"Unknown strategy: {strategy}")
            
            if not crawl_result.success:
                return result
            
            # Trích xuất và đánh giá nội dung
            extracted = self.extract_content(crawl_result)
            
            result.success = self.evaluate_content_quality(extracted)
            result.title = extracted["title"]
            result.content = extracted["content"]
            result.description = extracted["description"]
            result.html_size = extracted["html_size"]
            result.cleaned_text_size = extracted["cleaned_text_size"]
            result.is_404 = extracted["is_404"]
            
            return result
            
        except Exception as e:
            print(f"   ❌ Error with {strategy}: {str(e)}")
            return result
    
    async def crawl_url_with_fallback(self, crawler, url: str, base_config: CrawlerRunConfig) -> CrawlResult:
        """Crawl một URL với các chiến lược fallback tự động"""
        
        print(f"\n{'='*70}")
        print(f"🔍 Crawling: {url}")
        print('='*70)
        
        # Thử các chiến lược theo thứ tự
        strategies = [
            CrawlStrategy.DIRECT,
            CrawlStrategy.SPA_WITH_DELAY,
            CrawlStrategy.NAVIGATE_FROM_HOME
        ]
        
        for i, strategy in enumerate(strategies):
            print(f"   Trying strategy {i+1}/{len(strategies)}: {strategy}...", end=" ")
            
            result = await self.crawl_with_strategy(crawler, url, strategy, base_config)
            
            if result.success:
                print(f"✅ Success!")
                print(f"   📄 Title: {result.title}")
                print(f"   📊 Content: {result.cleaned_text_size:,} chars")
                return result
            else:
                print(f"❌ Failed")
                if result.is_404:
                    print(f"      (Page not found)")
                elif result.cleaned_text_size < self.min_content_length:
                    print(f"      (Content too short: {result.cleaned_text_size} chars)")
                else:
                    if result.html_size:
                        ratio = result.cleaned_text_size / result.html_size
                        print(f"      (Low text/html ratio: {ratio:.3f} < {self.min_cleaned_ratio})")
                    else:
                        print("      (Empty HTML)")
        
        # Tất cả chiến lược đều thất bại
        print(f"   ⚠️  All strategies failed for {url}")
        return result
    
    def save_result(self, result: CrawlResult):
        """Lưu kết quả vào file"""
        slug = self.slugify(result.title)
        filename = f"{slug}-{self.url_hash(result.url)}.md"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("---\n")
            f.write(f'title: "{result.title.replace(chr(34), chr(39))}"\n')
            f.write(f"url: {result.url}\n")
            f.write(f"strategy: {result.strategy}\n")
            if result.description:
                f.write(f'description: "{result.description.replace(chr(34), chr(39))}"\n')
            if result.is_404:
                f.write("status: 404\n")
            f.write("---\n\n")
            f.write(f"# {result.title}\n\n")
            if result.description:
                f.write(f"_{result.description}_\n\n")
            f.write(result.content)
        
        return filename
    
    async def crawl_urls(self, urls: list):
        """Crawl danh sách URLs"""
        
        print(f"🚀 Universal Crawler")
        print(f"📍 Base URL: {self.base_url}")
        print(f"🎯 Total URLs: {len(urls)}")
        print(f"📁 Output: {self.output_dir}")
        
        browser_cfg = BrowserConfig(
            browser_type="chromium",
            headless=True,
            verbose=False
        )
        
        base_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=0,
            verbose=False,
        )
        
        results = []
        
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            for url in urls:
                result = await self.crawl_url_with_fallback(crawler, url, base_config)
                
                if result.success:
                    filename = self.save_result(result)
                    print(f"   💾 Saved: {filename}")
                    results.append(result)
                else:
                    print(f"   ⚠️  Skipped (no valid content)")
                
                # Delay giữa các requests
                await asyncio.sleep(1)
        
        # Thống kê
        print(f"\n{'='*70}")
        print("📊 SUMMARY")
        print('='*70)
        print(f"Total URLs: {len(urls)}")
        print(f"Successfully crawled: {len(results)}")
        print(f"Failed: {len(urls) - len(results)}")
        
        if results:
            print(f"\n✅ Crawled pages:")
            strategy_counts = {}
            for r in results:
                strategy_counts[r.strategy] = strategy_counts.get(r.strategy, 0) + 1
                print(f"   - {r.title[:60]}: {r.cleaned_text_size:,} chars [{r.strategy}]")
            
            print(f"\n📈 Strategy usage:")
            for strategy, count in strategy_counts.items():
                print(f"   - {strategy}: {count} pages")
        
        print(f"\n📁 Output directory: {self.output_dir}")
        
        return results


# Ví dụ sử dụng
async def main():
    """Demo sử dụng Universal Crawler"""
    
    import sys
    
    # Nhận tham số đầu vào: có thể là domain root hoặc một URL cụ thể.
    if len(sys.argv) > 1:
        input_url = sys.argv[1].rstrip('/')
    else:
        input_url = "https://trieuvu.netlify.app"

    parsed = urlparse(input_url)
    root_base = f"{parsed.scheme}://{parsed.netloc}".rstrip('/')

    # Nếu người dùng truyền một URL có path (vd: /lien-he) thì vẫn dùng root domain làm base.
    # Khi đó ta crawl cả trang chủ rồi mới thử URL đích để hỗ trợ SPA navigation.
    if parsed.path and parsed.path not in ('', '/'):
        base_url = root_base
        urls = [root_base + '/', input_url]
    else:
        base_url = root_base
        # Các bundle preset cho một số site demo
        if base_url == "https://trieuvu.netlify.app":
            urls = [
                base_url + '/',
                base_url + '/gioi-thieu',
                base_url + '/dich-vu',
                base_url + '/bang-gia',
                base_url + '/tin-tuc',
                base_url + '/lien-he',
            ]
        elif base_url == "https://tuesy.net":
            urls = [
                "https://tuesy.net/le-thang-bay-cho-nhung-oan-hon-phieu-bat/",
                "https://tuesy.net/phuong-tien-thien-xao/",
                "https://tuesy.net/du-gia-bo-tat-gioi/",
            ]
        else:
            urls = [base_url + '/']
    
    # Cấu hình
    config = {
        'min_content_length': 200,
        # Giảm ratio mặc định để phù hợp các SPA nhiều markup
        'min_cleaned_ratio': 0.05,
    }
    
    # Tạo output directory dựa trên domain
    domain = urlparse(base_url).netloc.replace('.', '_')
    output_dir = f"crawled_{domain}"
    
    # Khởi tạo và chạy crawler
    crawler = UniversalCrawler(base_url, output_dir, config)
    results = await crawler.crawl_urls(urls)
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
