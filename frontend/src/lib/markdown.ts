import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

/** Plugins for every <ReactMarkdown>: GFM tables/lists plus $…$ / $$…$$ maths via KaTeX. */
export const mdPlugins = {
  remarkPlugins: [remarkGfm, remarkMath],
  rehypePlugins: [rehypeKatex],
};

/** For one-line text (claims, card previews): paragraphs render as spans. */
export const inlineMd = { ...mdPlugins, components: { p: "span" as const } };
