// Stands in for `lowlight` in the widget: the grammars a research chat's code blocks use,
// instead of the ~40 of lowlight's `common` set (the app keeps those).
import { createLowlight } from '../../node_modules/lowlight/lib/index.js';
import bash from 'highlight.js/lib/languages/bash';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import python from 'highlight.js/lib/languages/python';
import typescript from 'highlight.js/lib/languages/typescript';

export const common = { bash, javascript, json, python, typescript };
export const all = common;
export { createLowlight };
