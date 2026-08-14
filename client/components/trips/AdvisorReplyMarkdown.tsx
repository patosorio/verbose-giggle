"use client";

import { Fragment, type ReactNode } from "react";

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      nodes.push(
        <code
          key={key}
          className="rounded-[4px] bg-bg px-1 text-[0.9em]"
        >
          {token.slice(1, -1)}
        </code>
      );
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    key += 1;
    last = match.index + token.length;
  }
  if (last < text.length) {
    nodes.push(text.slice(last));
  }
  return nodes;
}

type Block =
  | { type: "p"; lines: string[] }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] };

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let ul: string[] = [];
  let ol: string[] = [];

  function flushParagraph() {
    if (paragraph.length === 0) return;
    blocks.push({ type: "p", lines: paragraph });
    paragraph = [];
  }

  function flushUl() {
    if (ul.length === 0) return;
    blocks.push({ type: "ul", items: ul });
    ul = [];
  }

  function flushOl() {
    if (ol.length === 0) return;
    blocks.push({ type: "ol", items: ol });
    ol = [];
  }

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trimEnd();
    if (line.trim() === "") {
      flushParagraph();
      flushUl();
      flushOl();
      continue;
    }
    const ulItem = /^[-*] (.+)$/.exec(line)?.[1];
    if (ulItem !== undefined) {
      flushParagraph();
      flushOl();
      ul.push(ulItem);
      continue;
    }
    const olItem = /^\d+\. (.+)$/.exec(line)?.[1];
    if (olItem !== undefined) {
      flushParagraph();
      flushUl();
      ol.push(olItem);
      continue;
    }
    flushUl();
    flushOl();
    paragraph.push(line);
  }
  flushParagraph();
  flushUl();
  flushOl();
  return blocks;
}

export function AdvisorReplyMarkdown({ text }: { text: string }) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const blocks = parseBlocks(trimmed);
  return (
    <div className="flex flex-col gap-2 text-sm">
      {blocks.map((block, index) => {
        if (block.type === "ul") {
          return (
            <ul key={index} className="list-disc space-y-1 pl-4">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInline(item)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "ol") {
          return (
            <ol key={index} className="list-decimal space-y-1 pl-4">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInline(item)}</li>
              ))}
            </ol>
          );
        }
        return (
          <p key={index}>
            {block.lines.map((line, lineIndex) => (
              <Fragment key={lineIndex}>
                {lineIndex > 0 ? <br /> : null}
                {renderInline(line)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
