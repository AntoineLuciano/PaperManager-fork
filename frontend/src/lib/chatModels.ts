import { useEffect, useState } from "react";
import { getMyAiKeyStatus } from "../api/client";

export type ChatModel = "claude" | "claude-work" | "claude-code" | "litellm";

export const CHAT_MODEL_LABELS: Record<ChatModel, string> = {
  claude: "Claude",
  "claude-work": "Claude (Work)",
  "claude-code": "Claude Code",
  litellm: "Gemma (LiteLLM)",
};

const BASE_MODELS: ChatModel[] = ["claude", "claude-work", "litellm"];

// "Claude Code" runs on the server owner's Claude subscription and the backend
// only enables it for users listed in CLAUDE_CODE_USERS, so ask before showing it.
export function useChatModels(): ChatModel[] {
  const [claudeCode, setClaudeCode] = useState(false);
  useEffect(() => {
    getMyAiKeyStatus()
      .then((s) => setClaudeCode(Boolean(s.claude_code_available)))
      .catch(() => setClaudeCode(false));
  }, []);
  return claudeCode ? ["claude-code", ...BASE_MODELS] : BASE_MODELS;
}
