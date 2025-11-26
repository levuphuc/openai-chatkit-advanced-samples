import { Sparkles, Palette, Target, Download } from "lucide-react";

import type { AdAssetRecord } from "../lib/ad-assets";

export function AdAssetCard({ asset }: { asset: AdAssetRecord }) {
  const handleDownload = async (imageUrl: string, index: number) => {
    try {
      // Use the image URL directly (proxy will handle routing)
      const url = imageUrl.startsWith("/") ? imageUrl : `/${imageUrl}`;
      
      // Fetch the image
      const response = await fetch(url);
      const blob = await response.blob();
      
      // Create download link
      const blobUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = `${asset.product.replace(/\s+/g, "-").toLowerCase()}-${index + 1}.png`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(blobUrl);
    } catch (error) {
      console.error("Failed to download image:", error);
      alert("Failed to download image. Please try again.");
    }
  };

  return (
    <li className="group rounded-2xl border border-slate-200/60 bg-white/80 p-5 shadow-[0_25px_70px_-50px_rgba(15,23,42,0.65)] transition-shadow hover:shadow-[0_35px_90px_-45px_rgba(15,23,42,0.55)] dark:border-slate-800/60 dark:bg-slate-900/70 dark:hover:shadow-[0_35px_90px_-40px_rgba(15,23,42,0.8)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200/60 bg-white/70 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-600 dark:border-slate-700/60 dark:bg-slate-800/70 dark:text-slate-300">
            <Target className="h-3.5 w-3.5" />
            {asset.product}
          </span>
          <h3 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            {asset.headline}
          </h3>
        </div>
        <div className="flex flex-col items-end gap-1 text-xs text-slate-500 dark:text-slate-400">
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-200/70 px-2 py-1 font-medium uppercase tracking-wide text-slate-700 dark:bg-slate-800/60 dark:text-slate-200">
            <Palette className="h-3.5 w-3.5" />
            {asset.style}
          </span>
          <span className="rounded-full bg-slate-100/70 px-2 py-1 font-medium uppercase tracking-wide text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
            {asset.tone}
          </span>
        </div>
      </div>

      <p className="mt-4 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {asset.primaryText}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
        <span className="font-semibold text-slate-700 dark:text-slate-200">
          Pitch:
        </span>
        <span>{asset.pitch}</span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-emerald-200/60 bg-emerald-50/70 px-3 py-2 text-sm font-semibold text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-900/30 dark:text-emerald-200">
        <Sparkles className="h-4 w-4" />
        {asset.callToAction}
      </div>

      {asset.images && asset.images.length > 0 && (
        <div className="mt-6 space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Generated images
          </h4>
          <div className="grid gap-3 sm:grid-cols-2">
            {asset.images.map((image, index) => (
              <div
                key={`${asset.id}-image-${index}`}
                className="relative overflow-hidden rounded-2xl border border-slate-200/60 bg-slate-50/80 shadow-sm transition-all hover:shadow-md dark:border-slate-800/60 dark:bg-slate-900/50 group"
              >
                <img
                  src={image}
                  alt={`${asset.product} concept ${index + 1}`}
                  className="h-full w-full object-cover"
                />
                {/* Download Button Overlay - Always visible on mobile, hover on desktop */}
                <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-t from-black/60 via-black/30 to-transparent opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity duration-200">
                  <button
                    onClick={() => handleDownload(image, index)}
                    className="flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-900 shadow-xl transition-all hover:scale-105 hover:bg-slate-50 active:scale-95 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
                    title="Download PNG"
                    type="button"
                  >
                    <Download className="h-4 w-4" />
                    <span>Download PNG</span>
                  </button>
                </div>
                {/* Alternative: Small download icon in corner - Always visible */}
                <button
                  onClick={() => handleDownload(image, index)}
                  className="absolute top-2 right-2 p-2 rounded-full bg-white/90 backdrop-blur-sm shadow-lg hover:bg-white hover:scale-110 active:scale-95 transition-all dark:bg-slate-800/90 dark:hover:bg-slate-800"
                  title="Download PNG"
                  type="button"
                >
                  <Download className="h-4 w-4 text-slate-700 dark:text-slate-200" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </li>
  );
}

