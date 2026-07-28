
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


export type PageResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};


export type ParseStatus = "pending" | "parsing" | "parsed" | "failed";


export type StudentResume = {
  id: number;
  name: string;
  email: string;
  phone: string;
  skills: string;
  education: string;
  research_experience: string;
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

export type UploadResult = StudentResume & {
  filename: string;
  warnings?: string[];
};


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


export type MatchResult = {
  student_name: string;
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


export type AdmissionOutput = {
  session_id: string;
  match_results: MatchResult[];


  adjustment_note?: string | null;
};

export type StudentChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type StudentChatResponse = {
  answer: string;
};

export type AppView = "match" | "library";
