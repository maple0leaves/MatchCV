import { useEffect, useRef, useState } from "react";
import { Bot, LoaderCircle, MessageCircle, Send, UserRound } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { StudentChatMessage } from "../types";

const QUICK_QUESTIONS = [
  "与期望条件有哪些匹配和差距？",
  "这名学生的主要优势是什么？",
  "有哪些风险需要在面试中核验？",
  "这个匹配分是怎么得出的？",
];

type StudentChatPanelProps = {
  studentName: string;
  messages: StudentChatMessage[];
  isSending: boolean;
  error: string;
  disabled?: boolean;
  onSend: (message: string) => Promise<boolean>;
};

export function StudentChatPanel({
  studentName,
  messages,
  isSending,
  error,
  disabled = false,
  onSend,
}: StudentChatPanelProps) {
  const [input, setInput] = useState("");
  const messageEndRef = useRef<HTMLDivElement>(null);
  const hasMountedRef = useRef(false);

  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, isSending]);

  const submit = async (value: string) => {
    const question = value.trim();
    if (!question || isSending || disabled) return;
    setInput("");
    const succeeded = await onSend(question);
    if (!succeeded) {
      setInput((current) => current || question);
    }
  };

  return (
    <section className="drawer-section student-chat">
      <div className="drawer-section-title">
        <MessageCircle size={16} />
        <h3>询问这名学生</h3>
      </div>

      <div className="student-chat-shell">
        <div className="student-chat-messages" aria-live="polite">
          {messages.length === 0 ? (
            <div className="student-chat-empty">
              <Bot size={20} />
              <p>
                可以继续询问 {studentName || "这名学生"} 的匹配点、差距、风险、
                评分依据或面试核验重点。
              </p>
            </div>
          ) : (
            messages.map((message, index) => (
              <div
                className={`student-chat-message is-${message.role}`}
                key={`${message.role}-${index}-${message.content.slice(0, 20)}`}
              >
                <span className="student-chat-avatar" aria-hidden="true">
                  {message.role === "assistant" ? <Bot size={14} /> : <UserRound size={14} />}
                </span>
                {message.role === "assistant" ? (
                  <div className="student-chat-bubble student-chat-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {message.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <p className="student-chat-bubble">{message.content}</p>
                )}
              </div>
            ))
          )}

          {isSending ? (
            <div className="student-chat-message is-assistant is-pending">
              <span className="student-chat-avatar" aria-hidden="true">
                <Bot size={14} />
              </span>
              <p className="student-chat-bubble">
                <LoaderCircle size={14} className="spin" /> 正在分析当前学生…
              </p>
            </div>
          ) : null}
          <div ref={messageEndRef} />
        </div>

        {messages.length === 0 ? (
          <div className="student-chat-suggestions" aria-label="快捷问题">
            {QUICK_QUESTIONS.map((question) => (
              <button
                type="button"
                key={question}
                disabled={isSending || disabled}
                onClick={() => void submit(question)}
              >
                {question}
              </button>
            ))}
          </div>
        ) : null}

        {error ? (
          <div className="student-chat-error" role="alert">
            {error} 问题已恢复到输入框，可直接重试。
          </div>
        ) : null}

        <form
          className="student-chat-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit(input);
          }}
        >
          <label htmlFor="student-chat-input">向 AI 询问当前学生</label>
          <div>
            <textarea
              id="student-chat-input"
              value={input}
              disabled={disabled}
              maxLength={1000}
              rows={3}
              placeholder={disabled ? "当前学生缺少可验证的简历来源" : "例如：这名学生有哪些匹配点和风险？"}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter"
                  && !event.shiftKey
                  && !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  void submit(input);
                }
              }}
            />
            <button
              type="submit"
              aria-label="发送学生问题"
              disabled={isSending || disabled}
            >
              {isSending ? <LoaderCircle size={16} className="spin" /> : <Send size={16} />}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
