import type {
  AuthUser,
  BatchUploadResult,
  CaptchaChallenge,
  StudentChatMessage,
  StudentChatResponse,
  StudentResume,
  LoginResponse,
  PageResponse,
  AdmissionOutput,
} from "../types";



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

export const studentApi = {
  list(params: { page?: number; page_size?: number; keyword?: string } = {}) {
    const query = new URLSearchParams();
    if (params.page) query.set("page", String(params.page));
    if (params.page_size) query.set("page_size", String(params.page_size));
    if (params.keyword) query.set("keyword", params.keyword);
    const qs = query.toString();
    return request<PageResponse<StudentResume>>(`/api/students${qs ? `?${qs}` : ""}`);
  },

  uploadBatch(files: File[]) {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<BatchUploadResult>("/api/students/upload/batch", {
      method: "POST",
      body: form,
    });
  },

  remove(id: number) {
    return request<void>(`/api/students/${id}`, { method: "DELETE" });
  },



  reparse(id: number) {
    return request<StudentResume>(`/api/students/${id}/reparse`, { method: "POST" });
  },



  getResumeFileBlob(id: number): Promise<Blob> {
    return fetchBlob(`/api/students/${id}/resume-file`);
  },



  getResumeFileBlobBySource(source: string): Promise<Blob> {
    return fetchBlob(`/api/students/resume-file?source=${encodeURIComponent(source)}`);
  },
};

export const admissionApi = {
  match(admissionDirection: string, admissionCriteria: string, topK: number) {
    const userInput = `招收方向：${admissionDirection}\n期望条件：${admissionCriteria}`;
    return request<AdmissionOutput>("/api/admission", {
      method: "POST",
      body: JSON.stringify({ user_input: userInput, top_k: topK }),
    });
  },

  refine(sessionId: string, message: string) {
    return request<AdmissionOutput>("/api/admission/refine", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, message }),
    });
  },

  chatWithStudent(
    sessionId: string,
    resumeSource: string,
    message: string,
    history: StudentChatMessage[],
  ) {
    return request<StudentChatResponse>("/api/admission/student-chat", {
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
