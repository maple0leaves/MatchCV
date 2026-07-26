import type {
  AuthUser,
  BatchUploadResult,
  CaptchaChallenge,
  CandidateChatMessage,
  CandidateChatResponse,
  LibraryResume,
  LoginResponse,
  PageResponse,
  RecruitmentOutput,
} from "../types";

// 开发环境下 vite.config.ts 已将 /api 代理到 Java 后端（默认 8080）；
// 生产环境可通过 VITE_API_BASE_URL 指向部署后的后端地址。
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") || "";

const TOKEN_KEY = "matchcv-token";
const USER_KEY = "matchcv-user";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

function persistSession(token: string, user: AuthUser) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    // Java 统一错误体 {error, message, status_code}；Python 透传时可能是 {detail}。
    return body?.message || body?.detail || `请求失败（${response.status}）`;
  } catch {
    return `请求失败（${response.status}）`;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    if (response.status === 401) clearSession();
    throw new ApiError(response.status, await extractErrorMessage(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function fetchBlob(path: string): Promise<Blob> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    if (response.status === 401) clearSession();
    throw new ApiError(response.status, await extractErrorMessage(response));
  }

  return response.blob();
}

export const authApi = {
  getCaptcha(): Promise<CaptchaChallenge> {
    return request<CaptchaChallenge>("/api/auth/captcha");
  },

  async login(username: string, password: string): Promise<AuthUser> {
    const data = await request<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    persistSession(data.access_token, data.user);
    return data.user;
  },

  async register(
    username: string,
    password: string,
    nickname: string,
    captchaId: string,
    captchaCode: string,
  ): Promise<AuthUser> {
    const data = await request<LoginResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        username,
        password,
        nickname,
        captcha_id: captchaId,
        captcha_code: captchaCode,
      }),
    });
    persistSession(data.access_token, data.user);
    return data.user;
  },

  async logout(): Promise<void> {
    try {
      await request("/api/auth/logout", { method: "POST" });
    } finally {
      clearSession();
    }
  },
};

export const candidateApi = {
  list(params: { page?: number; page_size?: number; keyword?: string } = {}) {
    const query = new URLSearchParams();
    if (params.page) query.set("page", String(params.page));
    if (params.page_size) query.set("page_size", String(params.page_size));
    if (params.keyword) query.set("keyword", params.keyword);
    const qs = query.toString();
    return request<PageResponse<LibraryResume>>(`/api/candidates${qs ? `?${qs}` : ""}`);
  },

  uploadBatch(files: File[]) {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<BatchUploadResult>("/api/candidates/upload/batch", {
      method: "POST",
      body: form,
    });
  },

  remove(id: number) {
    return request<void>(`/api/candidates/${id}`, { method: "DELETE" });
  },

  // 异步提交一次 AI 重新解析任务；返回值会立即进入 parsing/pending，
  // 后续由简历库已有的轮询逻辑刷新最终结果。
  reparse(id: number) {
    return request<LibraryResume>(`/api/candidates/${id}/reparse`, { method: "POST" });
  },

  // 简历原文接口需要携带 Authorization 头，无法直接用 <a href> 打开，
  // 因此以 blob 方式取回文件内容，交给调用方生成 object URL 做站内弹窗预览。
  getResumeFileBlob(id: number): Promise<Blob> {
    return fetchBlob(`/api/candidates/${id}/resume-file`);
  },

  // 智能匹配结果页只有 AI 返回的 resume_source 路径、没有学生 id，
  // 用同一份文件按路径查找的入口来预览。
  getResumeFileBlobBySource(source: string): Promise<Blob> {
    return fetchBlob(`/api/candidates/resume-file?source=${encodeURIComponent(source)}`);
  },
};

export const matchApi = {
  match(jobTitle: string, jobDescription: string, topK: number) {
    const userInput = `招收方向：${jobTitle}\n期望条件：${jobDescription}`;
    return request<RecruitmentOutput>("/api/recruit", {
      method: "POST",
      body: JSON.stringify({ user_input: userInput, top_k: topK }),
    });
  },

  refine(sessionId: string, message: string) {
    return request<RecruitmentOutput>("/api/recruit/refine", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, message }),
    });
  },

  chatWithCandidate(
    sessionId: string,
    resumeSource: string,
    message: string,
    history: CandidateChatMessage[],
  ) {
    return request<CandidateChatResponse>("/api/recruit/candidate-chat", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        resume_source: resumeSource,
        message,
        history: history.slice(-8),
      }),
    });
  },
};
