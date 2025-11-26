import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { ChatKit, useChatKit } from "@openai/chatkit-react";
import type { ColorScheme } from "../hooks/useColorScheme";
import {
  KNOWLEDGE_CHATKIT_API_DOMAIN_KEY,
  KNOWLEDGE_CHATKIT_API_URL,
  KNOWLEDGE_COMPOSER_PLACEHOLDER,
  KNOWLEDGE_GREETING,
  KNOWLEDGE_STARTER_PROMPTS,
} from "../lib/config";

type ChatKitPanelProps = {
  theme: ColorScheme;
  onThreadChange: (threadId: string | null) => void;
  onResponseCompleted: () => void;
};

type MessageTiming = {
  messageId: string;
  firstTokenTime: number; // Time to first token (TTFT) - client-side measurement
  completionTime: number; // Total response time - client-side measurement
  timestamp: Date;
  backendTTFT?: number; // TTFT from backend (OpenAI latency)
  backendCompletion?: number; // Total time from backend
};

export function ChatKitPanel({
  theme,
  onThreadChange,
  onResponseCompleted,
}: ChatKitPanelProps) {
  const [isResponding, setIsResponding] = useState(false);
  const [responseTime, setResponseTime] = useState<number | null>(null);
  const [firstTokenTime, setFirstTokenTime] = useState<number | null>(null);
  const startTimeRef = useRef<number | null>(null);
  const firstTokenTimeRef = useRef<number | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const currentMessageIdRef = useRef<string | null>(null);
  const messageTimingsRef = useRef<MessageTiming[]>([]);
  const [, setForceUpdate] = useState(0);

  const chatkit = useChatKit({
    api: {
      url: KNOWLEDGE_CHATKIT_API_URL,
      domainKey: KNOWLEDGE_CHATKIT_API_DOMAIN_KEY,
    },
    theme: {
      colorScheme: theme,
      color: {
        grayscale: {
          hue: 225,
          tint: 6,
          shade: theme === "dark" ? -1 : -4,
        },
        accent: {
          primary: theme === "dark" ? "#f1f5f9" : "#0f172a",
          level: 1,
        },
      },
      radius: "round",
    },
    startScreen: {
      greeting: KNOWLEDGE_GREETING,
      prompts: KNOWLEDGE_STARTER_PROMPTS,
    },
    composer: {
      placeholder: KNOWLEDGE_COMPOSER_PLACEHOLDER,
    },
    threadItemActions: {
      feedback: false,
    },
    onResponseStart: () => {
      // Start timing
      startTimeRef.current = Date.now();
      firstTokenTimeRef.current = null;
      currentMessageIdRef.current = `msg_${Date.now()}`;
      setIsResponding(true);
      setResponseTime(null);
      setFirstTokenTime(null);
      
      // Update time every 100ms
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
      intervalRef.current = setInterval(() => {
        if (startTimeRef.current) {
          const elapsed = (Date.now() - startTimeRef.current) / 1000;
          setResponseTime(elapsed);
          
          // Record first token time on first update (after initial response starts streaming)
          if (firstTokenTimeRef.current === null && elapsed > 0.05) {
            firstTokenTimeRef.current = elapsed;
            setFirstTokenTime(elapsed);
            console.log(`[Timing] First token: ${elapsed.toFixed(3)}s`);
          }
        }
      }, 100);
    },
    onLog: (event) => {
      // Log events for debugging and attempt to extract backend timing metadata
      console.log('[ChatKit Event]', event);
      
      // The event has shape: { name: string, data?: any }
      // When a thread.item.done event arrives with metadata, try to extract TTFT from backend
      try {
        const e = event as any;
        if (e && e.data && e.data.item && e.data.item.metadata) {
          const metadata = e.data.item.metadata;
          if (metadata.ttft !== undefined && metadata.completion_time !== undefined) {
            const backendTTFT = metadata.ttft;
            const backendCompletion = metadata.completion_time;
            
            console.log(`[Backend Timing] TTFT: ${backendTTFT}s, Total: ${backendCompletion}s`);
            
            // Update the last message's timing with backend data if available
            if (messageTimingsRef.current.length > 0) {
              const lastTiming = messageTimingsRef.current[messageTimingsRef.current.length - 1];
              // Store backend timing as a separate property for comparison/logging
              if (!lastTiming.backendTTFT) {
                lastTiming.backendTTFT = backendTTFT;
                lastTiming.backendCompletion = backendCompletion;
                setForceUpdate(prev => prev + 1); // Trigger re-render
              }
            }
          }
        }
      } catch (err) {
        // Silently ignore if event structure doesn't match expected format
        console.debug('[ChatKit Event] Could not extract metadata:', err);
      }
    },
    onResponseEnd: () => {
      // Stop timing and store final time
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      
      if (startTimeRef.current && currentMessageIdRef.current) {
        const finalTime = (Date.now() - startTimeRef.current) / 1000;
        const ttft = firstTokenTimeRef.current || 0;
        
        setResponseTime(finalTime);
        
        // Store timing data for this message
        const timing: MessageTiming = {
          messageId: currentMessageIdRef.current,
          firstTokenTime: ttft,
          completionTime: finalTime,
          timestamp: new Date(),
        };
        
        messageTimingsRef.current.push(timing);
        
        // Log timing information
        console.log(`[Timing] Message completed:`, {
          messageId: timing.messageId,
          firstTokenTime: `${ttft.toFixed(3)}s`,
          completionTime: `${finalTime.toFixed(3)}s`,
          timestamp: timing.timestamp.toISOString(),
        });
        
        // Log all message timings for debugging
        console.log(`[Timing] All messages (${messageTimingsRef.current.length}):`, 
          messageTimingsRef.current.map(t => ({
            id: t.messageId,
            ttft: `${t.firstTokenTime.toFixed(3)}s`,
            total: `${t.completionTime.toFixed(3)}s`,
            time: t.timestamp.toLocaleTimeString(),
          }))
        );
      }
      
      setIsResponding(false);
      startTimeRef.current = null;
      firstTokenTimeRef.current = null;
      currentMessageIdRef.current = null;
      
      onResponseCompleted();
      
      // Force update to trigger DOM injection with final timing
      setTimeout(() => setForceUpdate(prev => prev + 1), 50);
    },
    onThreadChange: ({ threadId }) => {
      onThreadChange(threadId ?? null);
    },
    onError: ({ error }) => {
      // ChatKit propagates the error to the UI; keep logging for debugging.
      console.error("ChatKit error", error);
      // Clean up timing on error
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      setIsResponding(false);
      setResponseTime(null);
      startTimeRef.current = null;
    },
  });

  // Portal target inside the KnowledgeDocumentsPanel (if present)
  const badgeRoot = typeof document !== "undefined" ? document.getElementById("timing-badge-root") : null;

  // Render the badges (used both for portal target and fallback)
  const badges = messageTimingsRef.current.length > 0 ? (
    <div className="flex flex-col gap-1">
      {messageTimingsRef.current.map((timing, index) => (
        <div
          key={timing.messageId}
          className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium shadow-lg backdrop-blur-sm"
          style={{
            background: theme === 'dark' ? 'rgba(71, 85, 105, 0.5)' : 'rgba(241, 245, 249, 0.9)',
            color: theme === 'dark' ? '#94a3b8' : '#64748b',
            border: `1px solid ${theme === 'dark' ? 'rgba(148, 163, 184, 0.2)' : 'rgba(100, 116, 139, 0.2)'}`,
          }}
        >
          <span>#{index + 1}</span>
          {/* Show backend TTFT if available, otherwise show client-side TTFT */}
          <span>
            TTFT: {timing.backendTTFT !== undefined ? timing.backendTTFT.toFixed(2) : timing.firstTokenTime.toFixed(2)}s
            {timing.backendTTFT !== undefined && <span className="text-[10px] opacity-70">(server)</span>}
          </span>
          <span>•</span>
          {/* Show backend completion time if available, otherwise show client-side */}
          <span>
            Total: {timing.backendCompletion !== undefined ? timing.backendCompletion.toFixed(1) : timing.completionTime.toFixed(1)}s
            {timing.backendCompletion !== undefined && <span className="text-[10px] opacity-70">(server)</span>}
          </span>
          <button
            onClick={() => {
              const ttft = timing.backendTTFT !== undefined ? timing.backendTTFT : timing.firstTokenTime;
              const total = timing.backendCompletion !== undefined ? timing.backendCompletion : timing.completionTime;
              const source = timing.backendTTFT !== undefined ? ' (backend)' : ' (client)';
              navigator.clipboard.writeText(
                `Message #${index + 1}: TTFT=${ttft.toFixed(3)}s, Total=${total.toFixed(3)}s${source}`
              );
            }}
            className="ml-1 opacity-60 hover:opacity-100 transition-opacity"
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px' }}
          >
            📋
          </button>
        </div>
      ))}
    </div>
  ) : null;

  // If the portal root exists, render badges into it (anchored inside the
  // KnowledgeDocumentsPanel). Otherwise fall back to rendering fixed so it's
  // still visible and doesn't overlap the composer.
  const portal = badgeRoot
    ? createPortal(
        <div className="absolute right-6 top-6 z-50 pointer-events-auto">{badges}</div>,
        badgeRoot
      )
    : badges && (
        <div className="fixed right-6 top-20 z-50">{badges}</div>
      );

  return (
    <div className="relative h-full w-full overflow-hidden border border-slate-200/60 bg-white shadow-card dark:border-slate-800/70 dark:bg-slate-900">
      <ChatKit control={chatkit.control} className="block h-full w-full" />
      {portal}
    </div>
  );
}
