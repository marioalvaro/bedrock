import Markdown from "react-markdown";

/**
 * A note's Markdown body. Raw HTML in the body is dropped (`skipHtml`), links open in a new tab,
 * and react-markdown's default URL transform removes `javascript:` links.
 */
export function NoteBody({ markdown }: { markdown: string }) {
  return (
    <div
      className={
        "space-y-2 text-sm [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-3 " +
        "[&_code]:bg-muted [&_code]:px-1 [&_h1]:font-medium [&_h2]:font-medium " +
        "[&_h3]:font-medium [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5"
      }
    >
      <Markdown
        skipHtml
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {markdown}
      </Markdown>
    </div>
  );
}
