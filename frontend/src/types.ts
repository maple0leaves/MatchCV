// 与 Java 后端 UserResponse 对齐
export type AuthUser = {
  id: number;
  username: string;
  nickname: string;
  role: string;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export type CaptchaChallenge = {
  captcha_id: string;
  image: string;
  expires_in_seconds: number;
};

// 与 Java 后端 PageResponse<T> 对齐
export type PageResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

// 简历解析状态：待解析 / 解析中 / 已解析 / 失败
export type ParseStatus = "pending" | "parsing" | "parsed" | "failed";

// 与 Java 后端 CandidateResponse 对齐
export type LibraryResume = {
  id: number;
  name: string;
  email: string;
  phone: string;
  skills: string;
  education: string;
  experience: string;
  status: string;
  resume_file_path: string;
  status_note: string;
  parse_status: ParseStatus;
  parsed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type UploadFailure = {
  filename: string;
  error: string;
};

export type UploadResult = LibraryResume & {
  filename: string;
  warnings?: string[];
};

// 与 Java 后端 CandidateController#uploadBatch 返回体对齐
export type BatchUploadResult = {
  items: UploadResult[];
  failures: UploadFailure[];
  success_count: number;
  failure_count: number;
  total_count: number;
};

export type ScoreBreakdown = {
  skill_points: number;
  education_points: number;
  rule_score: number | null;
  llm_score: number | null;
  rule_weight: number;
  llm_weight: number;
  final_score: number;
  calibration_status: "success" | "fallback" | "disabled" | "unavailable";
};

// 与 Python agent.schemas.MatchResult 对齐
export type MatchResult = {
  candidate_name: string;
  match_score: number;
  matched_skills: string[];
  missing_skills: string[];
  recommendation: string;
  should_proceed: boolean;
  resume_source: string;
  resume_text: string;
  education: string;
  score_breakdown: ScoreBreakdown;
  summary: string;
};

// 与 Python agent.schemas.RecruitmentOutput 对齐
export type RecruitmentOutput = {
  session_id: string;
  match_results: MatchResult[];
  // 仅 /api/recruit/refine 会赋值：这一轮反馈触发了期望条件调整时的说明文字
  // （正常完成时是变更摘要；Agent 未按预期走完检索+打分时是"仍是旧结果"的提示）。
  adjustment_note?: string | null;
};

export type CandidateChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type CandidateChatResponse = {
  answer: string;
};

export type AppView = "match" | "library";
