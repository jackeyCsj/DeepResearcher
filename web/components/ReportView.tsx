"use client";

import { useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeRaw from "rehype-raw";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

interface ReportViewProps {
  report: string;
  stats: { total_calls: number; total_tokens: number } | null;
  reportFileId: string | null;
  onClose: () => void;
}

interface SourceItem {
  id: string;
  text: string;
}

interface ProcessedReport {
  body: string;
  sourcesHeading: string;
  sources: SourceItem[];
}

function sanitizeMathDollars(text: string): string {
  // 单行 $$...$$ 拆成三行，remark-math 才识别为 display math
  const out = text.replace(/^\$\$(.+)\$\$$/gm, "$$$$\n$1\n$$$$");
  // 先保护真正的 LaTeX 对（$$...$$ 和 $...$），再转义剩余的独立 $数字（货币）
  const saved: string[] = [];
  const masked = out
    .replace(/\$\$[\s\S]*?\$\$/g, (m) => { saved.push(m); return `\x00M${saved.length - 1}\x00`; })
    .replace(/\$[^$\n]+\$/g, (m) => { saved.push(m); return `\x00M${saved.length - 1}\x00`; });
  const escaped = masked.replace(/\$(?=\d)/g, "\\$");
  return escaped.replace(/\x00M(\d+)\x00/g, (_, i) => saved[parseInt(i)]);
}

function processReport(raw: string): ProcessedReport {
  const headingMatch = raw.match(
    /^(#{1,3})\s*(Sources|References|参考文献)\s*$/m,
  );
  if (!headingMatch) {
    return {
      body: sanitizeMathDollars(raw),
      sourcesHeading: "",
      sources: [],
    };
  }

  const heading = headingMatch[0];
  const splitIdx = headingMatch.index!;
  const body = sanitizeMathDollars(raw.slice(0, splitIdx));
  const sourcesText = raw.slice(splitIdx + heading.length).trim();

  const processedBody = body.replace(
    /\[(\d+)\](?!\()/g,
    '<a href="#source-$1" class="citation-link">[$1]</a>',
  );

  const sources: SourceItem[] = [];
  for (const line of sourcesText.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const m = trimmed.match(/^\[(\d+)\]/);
    if (m) {
      sources.push({ id: m[1], text: trimmed });
    }
  }

  return { body: processedBody, sourcesHeading: heading, sources };
}

function handleCitationClick(e: React.MouseEvent<HTMLElement>) {
  const link = (e.target as HTMLElement).closest("a.citation-link");
  if (!link) return;
  e.preventDefault();
  const id = link.getAttribute("href")?.slice(1);
  if (!id) return;
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

const sourceComponents = {
  p: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
};

function extractTitle(md: string): string {
  const m = md.match(/^#\s+(.+)$/m);
  return m ? m[1].trim() : "research-report";
}

function downloadBlob(fileName: string, content: BlobPart, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export default function ReportView({ report, stats, reportFileId, onClose }: ReportViewProps) {
  const { body, sourcesHeading, sources } = processReport(report);
  const articleRef = useRef<HTMLElement>(null);
  const title = extractTitle(report);
  const baseName = (reportFileId || title).replace(/\.md$/i, "");

  function handlePrint() {
    const prev = document.title;
    document.title = title;
    window.print();
    setTimeout(() => { document.title = prev; }, 100);
  }

  function handleExportMarkdown() {
    downloadBlob(`${baseName}.md`, report, "text/markdown;charset=utf-8");
  }

  function handleExportWord() {
    const html = articleRef.current?.innerHTML || `<pre>${escapeHtml(report)}</pre>`;
    const doc = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title></head><body>${html}</body></html>`;
    downloadBlob(`${baseName}.doc`, doc, "application/msword;charset=utf-8");
  }

  return (
    <div className="px-10 pt-5 pb-20">
      <div className="print-hide mb-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={handleExportMarkdown}
            className="inline-flex items-center gap-1.5 rounded-lg border border-foreground/10 bg-surface px-3 py-1.5 text-[13px] text-foreground/70 transition-all duration-200 hover:border-border hover:bg-transparent hover:text-muted-foreground active:scale-95"
          >
            导出 MD
          </button>
          <button
            onClick={handleExportWord}
            className="inline-flex items-center gap-1.5 rounded-lg border border-foreground/10 bg-surface px-3 py-1.5 text-[13px] text-foreground/70 transition-all duration-200 hover:border-border hover:bg-transparent hover:text-muted-foreground active:scale-95"
          >
            导出 Word
          </button>
          <button
            onClick={handlePrint}
            className="inline-flex items-center gap-1.5 rounded-lg border border-foreground/10 bg-surface px-3 py-1.5 text-[13px] text-foreground/70 transition-all duration-200 hover:border-border hover:bg-transparent hover:text-muted-foreground active:scale-95"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10V4a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v6M5 10h14a2 2 0 0 1 2 2v3H3v-3a2 2 0 0 1 2-2z" />
              <circle cx="12" cy="15" r="1" />
            </svg>
            导出 PDF
          </button>
        </div>
        <button
          type="button"
          onClick={onClose}
          title="关闭文档"
          aria-label="关闭文档"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-foreground/10 bg-surface text-foreground/55 transition-colors hover:border-error/30 hover:text-error"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <article ref={articleRef} className="report-prose" onClick={handleCitationClick}>
        <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeRaw, rehypeKatex]}>
          {body}
        </ReactMarkdown>
        {sources.length > 0 && (
          <>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {sourcesHeading}
            </ReactMarkdown>
            {sources.map((s) => (
              <div key={s.id} id={`source-${s.id}`} className="source-item">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={sourceComponents}
                >
                  {s.text}
                </ReactMarkdown>
              </div>
            ))}
          </>
        )}
      </article>
      {stats && (
        <div className="mt-16 pt-4 border-t border-foreground/10 text-[13px] text-foreground/35 flex gap-6 font-mono">
          <span>{stats.total_calls} API calls</span>
          <span>{stats.total_tokens.toLocaleString()} tokens</span>
        </div>
      )}
    </div>
  );
}
