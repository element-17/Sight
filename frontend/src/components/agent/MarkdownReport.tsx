import { Fragment, type ReactNode } from "react";
import { classNames } from "../../classes";
import type { AgentEvidenceItem } from "../../types";
import styles from "./MarkdownReport.module.css";

const cx = classNames(styles);

function isSafeHttpUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function renderInline(
  text: string,
  evidence: Record<string, AgentEvidenceItem>,
  onSelectEvidence?: (eid: string) => void,
): ReactNode[] {
  const tokenRegex =
    /(\*\*[^*]+\*\*|`[^`]+`|\[([^\]]+)\]\(([^)\s]+)\)|\[(高置信|中置信|低置信)\]|\[(E\d+(?:\s*,\s*E\d+)*)\])/g;
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(
        <Fragment key={key++}>{text.slice(lastIndex, match.index)}</Fragment>,
      );
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(<strong key={key++}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(<code key={key++}>{token.slice(1, -1)}</code>);
    } else if (match[2] && match[3]) {
      const label = match[2];
      const href = match[3];
      if (isSafeHttpUrl(href)) {
        nodes.push(
          <a key={key++} href={href} target="_blank" rel="noreferrer">
            {label}
          </a>,
        );
      } else {
        nodes.push(<Fragment key={key++}>{label}</Fragment>);
      }
    } else if (match[4]) {
      const level = match[4];
      const cls =
        level === "高置信"
          ? "conf-high"
          : level === "中置信"
            ? "conf-mid"
            : "conf-low";
      nodes.push(
        <span key={key++} className={cx("conf-badge", cls)}>
          {level}
        </span>,
      );
    } else if (match[5]) {
      const eids = match[5]
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      eids.forEach((eid) => {
        const item = evidence[eid];
        nodes.push(
          <button
            key={key++}
            type="button"
            className={cx("cite-btn")}
            title={
              item
                ? `${eid} · ${item.title}\n${item.snippet}`
                : `查看证据 ${eid}`
            }
            onClick={() => onSelectEvidence?.(eid)}
          >
            {eid}
          </button>,
        );
      });
    }
    lastIndex = tokenRegex.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(<Fragment key={key++}>{text.slice(lastIndex)}</Fragment>);
  }
  return nodes;
}

export default function MarkdownReport({
  markdown,
  evidence = {},
  onSelectEvidence,
}: {
  markdown: string;
  evidence?: Record<string, AgentEvidenceItem>;
  onSelectEvidence?: (eid: string) => void;
}) {
  const lines = (markdown || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let blockKey = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;
      blocks.push(
        <pre key={blockKey++}>
          <code>{codeLines.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const headingMatch = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const content = renderInline(headingMatch[2], evidence, onSelectEvidence);
      if (level === 1) blocks.push(<h1 key={blockKey++}>{content}</h1>);
      else if (level === 2) blocks.push(<h2 key={blockKey++}>{content}</h2>);
      else blocks.push(<h3 key={blockKey++}>{content}</h3>);
      i++;
      continue;
    }

    if (/^[-*_]{3,}$/.test(trimmed)) {
      blocks.push(<hr key={blockKey++} />);
      i++;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      blocks.push(
        <blockquote key={blockKey++}>
          {renderInline(quoteLines.join(" "), evidence, onSelectEvidence)}
        </blockquote>,
      );
      continue;
    }

    if (/^[-*•]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={blockKey++}>
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item, evidence, onSelectEvidence)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i++;
      }
      blocks.push(
        <ol key={blockKey++}>
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item, evidence, onSelectEvidence)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,4}\s|[-*•]\s|\d+\.\s|>|```|[-*_]{3,}$)/.test(lines[i].trim())
    ) {
      paraLines.push(lines[i].trim());
      i++;
    }
    blocks.push(
      <p key={blockKey++}>
        {renderInline(paraLines.join(" "), evidence, onSelectEvidence)}
      </p>,
    );
  }

  return <div className={cx("markdown")}>{blocks}</div>;
}
