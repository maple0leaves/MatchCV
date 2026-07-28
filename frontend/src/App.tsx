import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Check,
  Database,
  Eye,
  EyeOff,
  ExternalLink,
  FileText,
  GraduationCap,
  LoaderCircle,
  LogIn,
  LogOut,
  Mail,
  Phone,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  X,
} from "lucide-react";
import { ApiError, authApi, studentApi, getStoredUser, admissionApi } from "./api/client";
import { StudentChatPanel } from "./components/StudentChatPanel";
import { defaultAdmissionCriteria } from "./data";
import type {
  AuthUser,
  CaptchaChallenge,
  StudentChatMessage,
  StudentResume,
  MatchResult,
  ParseStatus,
} from "./types";

type ScoreFilter = "all" | "excellent";
type MissionPhase = "idle" | "running" | "done";
type AppView = "match" | "library";
type AuthMode = "login" | "register";

const PARSE_STATUS_LABEL: Record<ParseStatus, string> = {
  pending: "待解析",
  parsing: "解析中",
  parsed: "已解析",
  failed: "解析失败",
};

function resumeDisplayName(resume: StudentResume) {
  if (resume.name && resume.name.trim()) return resume.name;
  const base = resume.resume_file_path?.split(/[\\/]/).pop() ?? "";
  return base.replace(/\.[^.]+$/, "") || `简历 #${resume.id}`;
}

function truncate(text: string, max: number) {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function isParseInProgress(status: ParseStatus) {
  return status === "pending" || status === "parsing";
}

export default function App() {
  const [view, setView] = useState<AppView>("match");
  const [admissionDirection, setAdmissionDirection] = useState("多模态大模型方向硕士");
  const [admissionCriteria, setAdmissionCriteria] = useState(defaultAdmissionCriteria);
  const [resultLimit, setResultLimit] = useState<number>(5);

  const [libraryResumes, setStudentResumes] = useState<StudentResume[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryQuery, setLibraryQuery] = useState("");
  const [isUploading, setIsUploading] = useState(false);

  const [query, setQuery] = useState("");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");
  const [phase, setPhase] = useState<MissionPhase>("idle");
  const [isCheckingLibrary, setIsCheckingLibrary] = useState(false);
  const [matchResults, setMatchResults] = useState<MatchResult[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [feedbackText, setFeedbackText] = useState("");
  const [isRefining, setIsRefining] = useState(false);
  const [adjustDrawerOpen, setAdjustDrawerOpen] = useState(false);
  const [adjustmentNote, setAdjustmentNote] = useState<string | null>(null);
  const [activeStudent, setActiveStudent] = useState<MatchResult | null>(null);
  const [studentChats, setStudentChats] = useState<Record<string, StudentChatMessage[]>>({});
  const [studentChatPendingKey, setStudentChatPendingKey] = useState<string | null>(null);
  const [studentChatErrors, setStudentChatErrors] = useState<Record<string, string>>({});
  const [activeResume, setActiveResume] = useState<StudentResume | null>(null);
  const [isOpeningResumeFile, setIsOpeningResumeFile] = useState(false);
  const [isReparsing, setIsReparsing] = useState(false);
  const [pdfPreview, setPdfPreview] = useState<{ url: string; title: string } | null>(null);
  const [pdfFrameLoaded, setPdfFrameLoaded] = useState(false);

  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser());
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authUsername, setAuthUsername] = useState("");
  const [authNickname, setAuthNickname] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authCaptcha, setAuthCaptcha] = useState<CaptchaChallenge | null>(null);
  const [authCaptchaCode, setAuthCaptchaCode] = useState("");
  const [authCaptchaLoading, setAuthCaptchaLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authSubmitting, setAuthSubmitting] = useState(false);

  const [toast, setToast] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const studentDrawerBodyRef = useRef<HTMLDivElement>(null);
  const resumeCloseRef = useRef<HTMLButtonElement>(null);
  const authCloseRef = useRef<HTMLButtonElement>(null);
  const adjustCloseRef = useRef<HTMLButtonElement>(null);
  const pdfPreviewCloseRef = useRef<HTMLButtonElement>(null);
  const resultsRef = useRef<HTMLElement>(null);
  const toastTimerRef = useRef<number | null>(null);
  const libraryQueryTimerRef = useRef<number | null>(null);

  const isAnalyzing = phase === "running";
  const isMatchSubmitting = isCheckingLibrary || isAnalyzing;
  const hasResults = phase === "done";
  const resumePoolCount = libraryResumes.length;
  const activeStudentChatKey = sessionId && activeStudent?.resume_source
    ? `${sessionId}:${activeStudent.resume_source}`
    : "";
  const activeStudentChatMessages = activeStudentChatKey
    ? studentChats[activeStudentChatKey] ?? []
    : [];

  const showToast = useCallback((message: string) => {
    setToast(message);
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2200);
  }, []);

  const loadAuthCaptcha = useCallback(async () => {
    setAuthCaptchaLoading(true);
    setAuthCaptchaCode("");
    try {
      setAuthCaptcha(await authApi.getCaptcha());
    } catch (error) {
      setAuthCaptcha(null);
      setAuthError(error instanceof ApiError ? error.message : "验证码加载失败，请稍后重试");
    } finally {
      setAuthCaptchaLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authOpen && authMode === "register") {
      void loadAuthCaptcha();
      return;
    }
    setAuthCaptcha(null);
    setAuthCaptchaCode("");
  }, [authMode, authOpen, loadAuthCaptcha]);

  const loadLibrary = useCallback(async (keyword?: string) => {
    setLibraryLoading(true);
    try {
      const data = await studentApi.list({ page: 1, page_size: 100, keyword });
      setStudentResumes(data.items);
    } catch (error) {
      showToast(error instanceof ApiError ? error.message : "加载简历库失败");
    } finally {
      setLibraryLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    if (user) loadLibrary();
  }, [user, loadLibrary]);

  useEffect(() => {
    if (!user) return;
    if (libraryQueryTimerRef.current) window.clearTimeout(libraryQueryTimerRef.current);
    libraryQueryTimerRef.current = window.setTimeout(() => {
      loadLibrary(libraryQuery.trim() || undefined);
    }, 300);
    return () => {
      if (libraryQueryTimerRef.current) window.clearTimeout(libraryQueryTimerRef.current);
    };

  }, [libraryQuery]);

  useEffect(() => {
    if (!user || !libraryResumes.some((resume) => isParseInProgress(resume.parse_status))) return;

    const timer = window.setInterval(async () => {
      const previousById = new Map(libraryResumes.map((resume) => [resume.id, resume]));
      try {
        const data = await studentApi.list({
          page: 1,
          page_size: 100,
          keyword: libraryQuery.trim() || undefined,
        });
        const completedWithWarning = data.items.find((resume) => {
          const previous = previousById.get(resume.id);
          return previous
            && isParseInProgress(previous.parse_status)
            && !isParseInProgress(resume.parse_status)
            && Boolean(resume.status_note)
            && resume.status_note !== "简历解析完成";
        });

        setStudentResumes(data.items);
        setActiveResume((current) => {
          if (!current) return current;
          return data.items.find((resume) => resume.id === current.id) ?? current;
        });
        if (completedWithWarning) {
          showToast(completedWithWarning.status_note);
        }
      } catch {

      }
    }, 3000);

    return () => window.clearInterval(timer);
  }, [libraryQuery, libraryResumes, showToast, user]);

  const resetAuthFields = () => {
    setAuthUsername("");
    setAuthNickname("");
    setAuthPassword("");
    setAuthCaptcha(null);
    setAuthCaptchaCode("");
    setShowPassword(false);
    setAuthError("");
  };

  const requireAuth = (actionLabel = "继续使用") => {
    if (user) return true;
    setAuthMode("login");
    resetAuthFields();
    setAuthError(`请先登录后再${actionLabel}`);
    setAuthOpen(true);
    showToast("请先登录后再使用");
    return false;
  };

  const openAuth = (mode: AuthMode) => {
    setAuthMode(mode);
    resetAuthFields();
    setAuthOpen(true);
  };

  const switchAuthMode = (mode: AuthMode) => {
    setAuthMode(mode);
    setAuthError("");
    setShowPassword(false);
  };

  const handleAuthSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const username = authUsername.trim();
    const nickname = authNickname.trim();
    const password = authPassword;
    if (username.length < 2) {
      setAuthError("用户名至少 2 个字符");
      return;
    }
    if (!password) {
      setAuthError("请输入密码");
      return;
    }
    if (authMode === "register" && (password.length < 8 || password.length > 32)) {
      setAuthError("密码长度需为 8-32 位");
      return;
    }
    if (authMode === "register" && (!authCaptcha || authCaptchaLoading)) {
      setAuthError("验证码正在加载，请稍后重试");
      return;
    }
    if (authMode === "register" && authCaptchaCode.trim().length < 4) {
      setAuthError("请输入图形验证码");
      return;
    }

    setAuthSubmitting(true);
    setAuthError("");
    try {
      const nextUser = authMode === "register"
        ? await authApi.register(
          username,
          password,
          nickname,
          authCaptcha!.captcha_id,
          authCaptchaCode.trim(),
        )
        : await authApi.login(username, password);
      setUser(nextUser);
      setAuthOpen(false);
      showToast(authMode === "register" ? `注册成功，欢迎 ${nextUser.nickname}` : `欢迎回来，${nextUser.nickname}`);
    } catch (error) {
      setAuthError(error instanceof ApiError ? error.message : "请求失败，请稍后重试");
      if (authMode === "register") {
        void loadAuthCaptcha();
      }
    } finally {
      setAuthSubmitting(false);
    }
  };

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch {

    }
    setUser(null);
    setPhase("idle");
    setMatchResults([]);
    setSessionId(null);
    setActiveStudent(null);
    setStudentChats({});
    setStudentChatErrors({});
    setStudentChatPendingKey(null);
    setActiveResume(null);
    setStudentResumes([]);
    setView("match");
    showToast("已退出登录");
  };

  const addResumes = async (files: FileList | File[] | null | undefined) => {
    if (!requireAuth("上传简历")) return;
    if (!files || files.length === 0) return;
    const fileArray = Array.from(files);
    setIsUploading(true);
    try {
      const result = await studentApi.uploadBatch(fileArray);
      await loadLibrary(libraryQuery.trim() || undefined);
      if (result.failure_count > 0) {
        showToast(`成功上传 ${result.success_count} 份，失败 ${result.failure_count} 份`);
      } else {
        showToast(`已上传 ${result.success_count} 份简历，正在解析`);
      }
    } catch (error) {
      showToast(error instanceof ApiError ? error.message : "上传失败，请稍后重试");
    } finally {
      setIsUploading(false);
    }
  };

  const removeResume = async (resume: StudentResume) => {
    if (!requireAuth("管理简历")) return;
    try {
      await studentApi.remove(resume.id);
      setStudentResumes((prev) => prev.filter((item) => item.id !== resume.id));
      setActiveResume((prev) => (prev?.id === resume.id ? null : prev));
      showToast("已从简历库移除");
    } catch (error) {
      showToast(error instanceof ApiError ? error.message : "删除失败，请稍后重试");
    }
  };

  const reparseResume = async (resume: StudentResume) => {
    if (!requireAuth("重新解析简历")) return;
    setIsReparsing(true);
    try {
      const updated = await studentApi.reparse(resume.id);
      setStudentResumes((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setActiveResume((prev) => (prev?.id === updated.id ? updated : prev));
      showToast("已提交重新解析任务");
    } catch (error) {
      showToast(error instanceof ApiError ? error.message : "重新解析失败，请稍后重试");
    } finally {
      setIsReparsing(false);
    }
  };

  const closePdfPreview = () => {
    setPdfPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return null;
    });
  };

  const openPdfPreview = async (fetchBlob: () => Promise<Blob>, title: string) => {
    setIsOpeningResumeFile(true);
    try {
      const blob = await fetchBlob();
      const url = URL.createObjectURL(blob);
      setPdfFrameLoaded(false);
      setPdfPreview((prev) => {
        if (prev) URL.revokeObjectURL(prev.url);
        return { url, title };
      });
    } catch (error) {
      showToast(error instanceof ApiError ? error.message : "打开原始简历失败，请稍后重试");
    } finally {
      setIsOpeningResumeFile(false);
    }
  };

  const openStudentResumePdf = (resume: StudentResume) => {
    void openPdfPreview(() => studentApi.getResumeFileBlob(resume.id), resumeDisplayName(resume));
  };

  const openMatchResumePdf = (student: MatchResult) => {
    if (!student.resume_source) return;
    void openPdfPreview(
      () => studentApi.getResumeFileBlobBySource(student.resume_source),
      student.student_name || "学生简历",
    );
  };

  const startAnalysis = async () => {
    if (!requireAuth("开始匹配")) return;
    if (!admissionDirection.trim()) {
      showToast("请先填写招收方向");
      return;
    }
    if (/博士|硕博/.test(admissionDirection)) {
      showToast("当前仅支持硕士研究生申请筛选");
      return;
    }
    if (!admissionCriteria.trim()) {
      showToast("请先填写期望条件");
      return;
    }

    setIsCheckingLibrary(true);
    try {
      const library = await studentApi.list({ page: 1, page_size: 1 });
      if (library.total === 0) {
        showToast("简历库为空，请先上传简历");
        return;
      }
    } catch (error) {
      showToast(error instanceof ApiError ? error.message : "检查简历库失败，请稍后重试");
      return;
    } finally {
      setIsCheckingLibrary(false);
    }

    setPhase("running");
    setActiveStudent(null);
    setSessionId(null);
    setAdjustmentNote(null);
    setStudentChats({});
    setStudentChatErrors({});
    setStudentChatPendingKey(null);
    setView("match");

    try {
      const result = await admissionApi.match(admissionDirection.trim(), admissionCriteria.trim(), resultLimit);
      setMatchResults(result.match_results);
      setSessionId(result.session_id);
      setPhase("done");
      showToast(`匹配完成，共返回 ${result.match_results.length} 位学生`);
      window.setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (error) {
      setPhase("idle");
      showToast(error instanceof ApiError ? error.message : "匹配失败，请稍后重试");
    }
  };

  const submitFeedback = async () => {
    if (!sessionId || !feedbackText.trim()) return;
    setIsRefining(true);
    try {
      const result = await admissionApi.refine(sessionId, feedbackText.trim());
      setMatchResults(result.match_results);
      setActiveStudent(null);
      setStudentChats({});
      setStudentChatErrors({});
      setStudentChatPendingKey(null);
      setFeedbackText("");
      setAdjustmentNote(result.adjustment_note ?? "已根据反馈更新匹配结果");
      setAdjustDrawerOpen(false);
      showToast("调整成功");
    } catch (error) {
      showToast(error instanceof ApiError ? error.message : "调整失败，请稍后重试");
    } finally {
      setIsRefining(false);
    }
  };

  const sendStudentQuestion = async (message: string): Promise<boolean> => {
    const student = activeStudent;
    const currentSessionId = sessionId;
    if (!student || !currentSessionId || !student.resume_source) return false;

    const chatKey = `${currentSessionId}:${student.resume_source}`;
    const history = studentChats[chatKey] ?? [];
    const optimisticHistory: StudentChatMessage[] = [
      ...history,
      { role: "user", content: message },
    ];

    setStudentChats((prev) => ({
      ...prev,
      [chatKey]: [
        ...(prev[chatKey] ?? history),
        { role: "user", content: message },
      ],
    }));
    setStudentChatPendingKey(chatKey);
    setStudentChatErrors((prev) => ({ ...prev, [chatKey]: "" }));

    try {
      const result = await admissionApi.chatWithStudent(
        currentSessionId,
        student.resume_source,
        message,
        history,
      );
      setStudentChats((prev) => ({
        ...prev,
        [chatKey]: [
          ...(prev[chatKey] ?? optimisticHistory),
          { role: "assistant", content: result.answer },
        ],
      }));
      return true;
    } catch (error) {
      setStudentChats((prev) => ({
        ...prev,
        [chatKey]: history,
      }));
      setStudentChatErrors((prev) => ({
        ...prev,
        [chatKey]: error instanceof ApiError ? error.message : "学生分析失败，请稍后重试",
      }));
      return false;
    } finally {
      setStudentChatPendingKey((current) => (current === chatKey ? null : current));
    }
  };

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
      if (libraryQueryTimerRef.current) window.clearTimeout(libraryQueryTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!activeStudent) return;
    const frame = window.requestAnimationFrame(() => {
      if (studentDrawerBodyRef.current) {
        studentDrawerBodyRef.current.scrollTop = 0;
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeStudent]);

  useEffect(() => {
    const overlayOpen = Boolean(activeStudent || activeResume || authOpen || pdfPreview || adjustDrawerOpen);
    document.body.classList.toggle("drawer-open", overlayOpen);
    if (pdfPreview) pdfPreviewCloseRef.current?.focus();
    else if (activeStudent) closeButtonRef.current?.focus();
    else if (activeResume) resumeCloseRef.current?.focus();
    else if (authOpen) authCloseRef.current?.focus();
    else if (adjustDrawerOpen) adjustCloseRef.current?.focus();

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;

      if (pdfPreview) closePdfPreview();
      else if (activeStudent) setActiveStudent(null);
      else if (activeResume) setActiveResume(null);
      else if (authOpen) setAuthOpen(false);
      else if (adjustDrawerOpen) setAdjustDrawerOpen(false);
    };

    if (overlayOpen) window.addEventListener("keydown", handleEscape);
    return () => {
      document.body.classList.remove("drawer-open");
      window.removeEventListener("keydown", handleEscape);
    };
  }, [activeStudent, activeResume, authOpen, pdfPreview, adjustDrawerOpen]);

  const visibleStudents = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return matchResults
      .filter((student) => {
        if (scoreFilter === "excellent" && student.match_score < 85) return false;
        if (!keyword) return true;
        return [
          student.student_name,
          student.recommendation,
          ...student.matched_skills,
          ...student.missing_skills,
        ].some((value) => value.toLowerCase().includes(keyword));
      })
      .sort((a, b) => b.match_score - a.match_score);
  }, [query, scoreFilter, matchResults]);

  return (
    <div className={`app-shell phase-${phase} view-${view}`}>
      <div className="ambient-noise" aria-hidden="true" />
      <div className="ambient-glow" aria-hidden="true" />

      <header className="topbar">
        <div className="topbar-inner">
          <button className="brand" type="button" aria-label="MatchCV" onClick={() => setView("match")}>
            <span className="brand-name">MatchCV</span>
            <span className="brand-badge">LAB</span>
          </button>

          <div className="topbar-status">
            <button
              className={`pool-btn ${view === "library" ? "is-active" : ""}`}
              type="button"
              onClick={() => {
                if (!requireAuth("查看简历库")) return;
                setView("library");
              }}
            >
              <Database size={14} />
              简历库
              <strong>{resumePoolCount}</strong>
            </button>
            <div className={`status-pill ${isAnalyzing ? "is-active" : ""}`}>
              <i />
              <span>{isAnalyzing ? "匹配进行中" : "系统就绪"}</span>
            </div>
            {user ? (
              <div className="user-chip">
                <span><UserRound size={14} /> {user.nickname}</span>
                <button type="button" className="logout-btn" onClick={handleLogout} aria-label="退出登录">
                  <LogOut size={14} />
                </button>
              </div>
            ) : (
              <button className="auth-entry" type="button" onClick={() => openAuth("login")}>
                <LogIn size={14} />
                登录 / 注册
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="main-stage">
        {view === "library" ? (
          <section className="library-page" aria-labelledby="library-title">
            <div className="library-hero">
              <button className="back-link" type="button" onClick={() => setView("match")}>
                <ArrowLeft size={16} />
                返回匹配
              </button>
              <h1 id="library-title">简历库</h1>
              <p>上传并管理学生简历，匹配时自动纳入检索</p>
            </div>

            <div
              className={`upload-zone library-upload ${isDragOver ? "is-dragover" : ""} ${isUploading ? "is-busy" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={(event) => {
                event.preventDefault();
                setIsDragOver(false);
              }}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragOver(false);
                addResumes(event.dataTransfer.files);
              }}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
            >
              {isUploading ? <LoaderCircle size={24} className="spin" /> : <Upload size={24} />}
              <strong>{isUploading ? "正在上传…" : "拖拽或点击上传简历"}</strong>
              <span>支持 PDF / PNG / JPG，可多选</span>
            </div>
            <input
              ref={fileInputRef}
              className="visually-hidden"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg"
              multiple
              onChange={(event) => {
                addResumes(event.target.files);
                event.target.value = "";
              }}
            />

            <div className="library-toolbar">
              <div className="section-header library-count">
                <h2>全部简历</h2>
                <span className="count-chip">{libraryResumes.length}</span>
              </div>
              <label className="search-box">
                <Search size={15} />
                <span className="visually-hidden">搜索简历库</span>
                <input
                  value={libraryQuery}
                  onChange={(event) => setLibraryQuery(event.target.value)}
                  placeholder="搜索姓名、技能或联系方式"
                />
              </label>
            </div>

            <div className="library-grid" aria-busy={libraryLoading}>
              {libraryLoading ? (
                <>
                  <span className="visually-hidden" role="status">正在加载简历列表…</span>
                  {Array.from({ length: 6 }).map((_, index) => (
                    <div
                      className="resume-card skeleton-card"
                      key={`skeleton-${index}`}
                      aria-hidden="true"
                      style={{ animationDelay: `${index * 50}ms` }}
                    >
                      <div className="resume-card-top">
                        <span className="skeleton-chip" />
                        <span className="skeleton-icon" />
                      </div>
                      <div className="resume-card-body">
                        <span className="skeleton-line skeleton-line-title" />
                        <span className="skeleton-line skeleton-line-sub" />
                        <span className="skeleton-line skeleton-line-small" />
                      </div>
                      <div className="resume-card-footer">
                        <span className="skeleton-line skeleton-line-btn" />
                        <span className="skeleton-icon skeleton-icon-sm" />
                      </div>
                    </div>
                  ))}
                </>
              ) : (
                <>
                  {libraryResumes.map((resume, index) => (
                    <article
                      className="resume-card"
                      key={resume.id}
                      style={{ animationDelay: `${index * 40}ms` }}
                    >
                      <div className="resume-card-top">
                        <span className={`resume-badge status-${resume.parse_status}`}>
                          {PARSE_STATUS_LABEL[resume.parse_status] ?? resume.parse_status}
                        </span>
                        <FileText size={18} />
                      </div>
                      <div className="resume-card-body">
                        <strong>{resumeDisplayName(resume)}</strong>
                        <span>{resume.skills ? truncate(resume.skills, 60) : "技能待解析"}</span>
                        <p className="resume-summary">
                          {resume.research_experience || "AI 摘要生成中…"}
                        </p>
                        {resume.status_note && resume.status_note !== "简历解析完成" ? (
                          <em>{truncate(resume.status_note, 40)}</em>
                        ) : null}
                      </div>
                      <div className="resume-card-footer">
                        <button
                          className="secondary-button resume-action"
                          type="button"
                          onClick={() => setActiveResume(resume)}
                        >
                          <Eye size={14} />
                          详情
                        </button>
                        <button
                          className="icon-button danger"
                          type="button"
                          aria-label={`删除 ${resumeDisplayName(resume)}`}
                          onClick={() => removeResume(resume)}
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </article>
                  ))}

                  {libraryResumes.length === 0 ? (
                    <div className="empty-state">
                      <Search size={20} />
                      <strong>没有找到简历</strong>
                      <span>试试其他关键词，或上传新简历</span>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </section>
        ) : (
          <>
            <section className="hero-section" aria-labelledby="hero-title">
              <div className="hero-backdrop" aria-hidden="true">
                <span className="hero-orb hero-orb-a" />
                <span className="hero-orb hero-orb-b" />
                <span className="hero-orb hero-orb-c" />
                <div className="hero-grid" />
                <div className="hero-lines" />
              </div>
              <h1 id="hero-title" className="slogan-main">LET TALENT SURFACE</h1>
              <p className="slogan-sub">让人才被看见</p>

              <div className={`compose-panel ${isAnalyzing ? "is-busy" : ""}`}>
                <div className="field">
                  <label htmlFor="admission-direction">招收方向</label>
                  <input
                    id="admission-direction"
                    value={admissionDirection}
                    onChange={(event) => setAdmissionDirection(event.target.value)}
                    placeholder="例如：多模态大模型方向硕士"
                  />
                </div>

                <div className="field">
                  <label htmlFor="admission-criteria">期望条件</label>
                  <textarea
                    id="admission-criteria"
                    value={admissionCriteria}
                    onChange={(event) => setAdmissionCriteria(event.target.value)}
                    spellCheck={false}
                    placeholder="描述希望学生具备的研究方向、专业背景、科研经历、技术能力及加分项…"
                  />
                </div>

                <div className="field field-inline">
                  <label htmlFor="result-limit">匹配数量</label>
                  <div className="limit-row">
                    <input
                      id="result-limit"
                      type="number"
                      min={1}
                      max={30}
                      value={resultLimit}
                      onChange={(event) => {
                        const next = Number(event.target.value);
                        if (!Number.isFinite(next)) return;
                        setResultLimit(Math.min(30, Math.max(1, Math.floor(next))));
                      }}
                    />
                  </div>
                </div>

                <div className="compose-footer">
                  <button className="run-button" type="button" onClick={startAnalysis} disabled={isMatchSubmitting}>
                    {isMatchSubmitting ? <LoaderCircle size={17} className="spin" /> : null}
                    {isCheckingLibrary ? "CHECKING…" : isAnalyzing ? "MATCHING…" : hasResults ? "RE-RUN MATCH" : "START MATCH"}
                  </button>
                </div>
              </div>
            </section>

            {hasResults || isAnalyzing ? (
              <section
                ref={resultsRef}
                className={`results-section ${isAnalyzing ? "is-updating" : ""}`}
                aria-labelledby="results-title"
              >
                <div className="section-header">
                  <h2 id="results-title">推荐结果</h2>
                  <span className="count-chip">{visibleStudents.length} RESUMES</span>
                </div>

                <div className="result-toolbar">
                  <label className="search-box">
                    <Search size={15} />
                    <span className="visually-hidden">搜索推荐结果</span>
                    <input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="搜索姓名或技能"
                    />
                  </label>
                  <div className="filter-segment" aria-label="匹配度筛选">
                    <button className={scoreFilter === "all" ? "is-active" : ""} type="button" onClick={() => setScoreFilter("all")}>全部</button>
                    <button className={scoreFilter === "excellent" ? "is-active" : ""} type="button" onClick={() => setScoreFilter("excellent")}>85+</button>
                  </div>
                  {hasResults && sessionId ? (
                    <button
                      className="adjust-trigger"
                      type="button"
                      onClick={() => setAdjustDrawerOpen(true)}
                    >
                      <Sparkles size={14} />
                      调整结果
                    </button>
                  ) : null}
                </div>

                <div className="student-grid" aria-live="polite">
                  {visibleStudents.map((student, index) => (
                    <article
                      className="student-card"
                      key={`${student.student_name}-${index}`}
                      style={{ animationDelay: `${index * 55}ms` }}
                    >
                      <div className="student-card-top">
                        <div className="match-score" aria-label={`匹配度 ${student.match_score}`}>
                          <span>匹配度</span>
                          <strong>{student.match_score}</strong>
                        </div>
                      </div>

                      <div className="student-person">
                        <div>
                          <strong>{student.student_name || "未知学生"}</strong>
                          <span className={`proceed-tag ${student.should_proceed ? "is-yes" : "is-no"}`}>
                            {student.should_proceed ? "建议推荐面试" : "暂不推荐"}
                          </span>
                          {student.education ? (
                            <small className="student-meta">
                              {student.education}
                            </small>
                          ) : null}
                        </div>
                      </div>

                      <div className="skill-chip-group">
                        {student.matched_skills.slice(0, 4).map((skill) => (
                          <span className="skill-chip matched" key={skill}>{skill}</span>
                        ))}
                      </div>

                      <p className="match-summary">{student.recommendation || "暂无推荐说明"}</p>

                      <div className="student-card-footer">
                        <button
                          className="inspect-button"
                          type="button"
                          aria-label={`查看 ${student.student_name} 的匹配依据`}
                          onClick={() => setActiveStudent(student)}
                        >
                          查看依据
                        </button>
                      </div>
                    </article>
                  ))}

                  {visibleStudents.length === 0 ? (
                    <div className="empty-state">
                      <Search size={20} />
                      <strong>没有找到匹配的学生</strong>
                      <span>尝试更换搜索词或筛选条件</span>
                    </div>
                  ) : null}
                </div>
              </section>
            ) : null}
          </>
        )}
      </main>

      {authOpen ? (
        <div
          className="drawer-layer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAuthOpen(false);
          }}
        >
          <div className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-title">
            <header className="auth-modal-header">
              <h2 id="auth-title">{authMode === "login" ? "用户登录" : "新用户注册"}</h2>
              <button
                ref={authCloseRef}
                className="auth-close"
                type="button"
                onClick={() => setAuthOpen(false)}
                aria-label="关闭登录窗口"
              >
                <X size={18} />
              </button>
            </header>

            <form className="auth-form" onSubmit={handleAuthSubmit}>
              <label className="auth-field">
                <span>USERNAME</span>
                <div className="auth-input">
                  <input
                    value={authUsername}
                    onChange={(event) => setAuthUsername(event.target.value)}
                    placeholder="请输入用户名"
                    autoComplete="username"
                    autoFocus
                  />
                </div>
              </label>

              <label className="auth-field">
                <span>PASSWORD</span>
                <div className="auth-input">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={authPassword}
                    onChange={(event) => setAuthPassword(event.target.value)}
                    placeholder="请输入密码"
                    autoComplete={authMode === "login" ? "current-password" : "new-password"}
                  />
                  <button
                    type="button"
                    className="auth-eye"
                    onClick={() => setShowPassword((prev) => !prev)}
                    aria-label={showPassword ? "隐藏密码" : "显示密码"}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </label>

              {authMode === "register" ? (
                <>
                  <label className="auth-field">
                    <span>NICKNAME</span>
                    <div className="auth-input">
                      <input
                        value={authNickname}
                        onChange={(event) => setAuthNickname(event.target.value)}
                        placeholder="展示给他人的名称（选填）"
                        autoComplete="nickname"
                        maxLength={20}
                      />
                    </div>
                  </label>

                  <div className="auth-field">
                    <label htmlFor="auth-captcha-code">
                      CAPTCHA
                    </label>
                    <div className="auth-captcha-row">
                      <div className="auth-input">
                        <input
                          id="auth-captcha-code"
                          value={authCaptchaCode}
                          onChange={(event) => setAuthCaptchaCode(event.target.value.toUpperCase())}
                          placeholder="输入图中字符"
                          autoComplete="off"
                          autoCapitalize="characters"
                          spellCheck={false}
                          maxLength={8}
                        />
                      </div>
                      <button
                        className="auth-captcha-image"
                        type="button"
                        disabled={authCaptchaLoading}
                        onClick={() => {
                          setAuthError("");
                          void loadAuthCaptcha();
                        }}
                        aria-label="刷新图形验证码"
                        title="点击刷新验证码"
                      >
                        {authCaptchaLoading ? (
                          <LoaderCircle size={18} className="spin" />
                        ) : authCaptcha ? (
                          <img src={authCaptcha.image} alt="图形验证码" />
                        ) : (
                          <RefreshCw size={18} />
                        )}
                      </button>
                    </div>
                    <small className="auth-captcha-hint">看不清？点击图片换一张</small>
                  </div>
                </>
              ) : null}

              {authError ? <div className="auth-error">{authError}</div> : null}

              <button
                className="auth-submit"
                type="submit"
                disabled={authSubmitting || (authMode === "register" && authCaptchaLoading)}
              >
                {authSubmitting ? <LoaderCircle size={16} className="spin" /> : null}
                {authMode === "login" ? "登录" : "提交注册"}
              </button>
            </form>

            <footer className="auth-modal-footer">
              {authMode === "login" ? (
                <span>没有账号？<button type="button" onClick={() => switchAuthMode("register")}>去注册</button></span>
              ) : (
                <span>已有账号？<button type="button" onClick={() => switchAuthMode("login")}>去登录</button></span>
              )}
            </footer>
          </div>
        </div>
      ) : null}

      {activeStudent ? (
        <div
          className="drawer-layer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setActiveStudent(null);
          }}
        >
          <aside className="student-drawer" role="dialog" aria-modal="true" aria-labelledby="student-name">
            <header className="drawer-header">
              <div className="drawer-code">
                <span>MATCH EVIDENCE</span>
                <span className="confidence"><Sparkles size={13} /> 推荐依据</span>
              </div>
              <button
                ref={closeButtonRef}
                className="icon-button"
                type="button"
                onClick={() => setActiveStudent(null)}
                aria-label="关闭学生详情"
              >
                <X size={18} />
              </button>
            </header>

            <div ref={studentDrawerBodyRef} className="drawer-body">
              <section className="student-profile">
                <div>
                  <h2 id="student-name">{activeStudent.student_name || "未知学生"}</h2>
                  <p>{activeStudent.should_proceed ? "建议推荐面试" : "暂不推荐"}</p>
                  {activeStudent.education ? (
                    <span>{activeStudent.education}</span>
                  ) : null}
                </div>
                <div className="drawer-score">
                  <strong>{activeStudent.match_score}</strong>
                  <span>匹配度</span>
                </div>
              </section>

              <section className="drawer-section ai-summary">
                <div className="drawer-section-title"><Bot size={16} /><h3>AI 推荐结论</h3></div>
                <p>{activeStudent.recommendation || "暂无推荐说明"}</p>
              </section>

              <section className="drawer-section">
                <div className="drawer-section-title">
                  <Check size={16} />
                  <h3>匹配技能</h3>
                  <span>{activeStudent.matched_skills.length} 项</span>
                </div>
                <div className="skill-chip-group">
                  {activeStudent.matched_skills.length > 0 ? (
                    activeStudent.matched_skills.map((skill) => (
                      <span className="skill-chip matched" key={skill}>{skill}</span>
                    ))
                  ) : (
                    <p className="skill-chip-empty">暂无明确匹配技能</p>
                  )}
                </div>
              </section>

              <section className="drawer-section risk-section">
                <div className="drawer-section-title"><AlertTriangle size={16} /><h3>需要关注</h3></div>
                <div className="skill-chip-group">
                  {activeStudent.missing_skills.length > 0 ? (
                    activeStudent.missing_skills.map((skill) => (
                      <span className="skill-chip missing" key={skill}>{skill}</span>
                    ))
                  ) : (
                    <p>暂无明显技能缺口</p>
                  )}
                </div>
              </section>

              <section className="drawer-section ai-summary">
                <div className="drawer-section-title"><FileText size={16} /><h3>AI 简历摘要</h3></div>
                <p>{activeStudent.summary || "暂无摘要"}</p>
              </section>

              <StudentChatPanel
                studentName={activeStudent.student_name}
                messages={activeStudentChatMessages}
                isSending={studentChatPendingKey === activeStudentChatKey}
                error={activeStudentChatKey ? studentChatErrors[activeStudentChatKey] ?? "" : ""}
                disabled={!sessionId || !activeStudent.resume_source}
                onSend={sendStudentQuestion}
              />
            </div>

            <footer className="drawer-footer">
              <button className="secondary-button" type="button" onClick={() => setActiveStudent(null)}>
                关闭
              </button>
              <button
                className="primary-button"
                type="button"
                disabled={isOpeningResumeFile || !activeStudent.resume_source}
                onClick={() => openMatchResumePdf(activeStudent)}
              >
                {isOpeningResumeFile ? <LoaderCircle size={15} className="spin" /> : <ExternalLink size={15} />}
                查看原始简历
              </button>
            </footer>
          </aside>
        </div>
      ) : null}

      {activeResume ? (
        <div
          className="drawer-layer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setActiveResume(null);
          }}
        >
          <aside className="student-drawer" role="dialog" aria-modal="true" aria-labelledby="resume-detail-name">
            <header className="drawer-header">
              <div className="drawer-code">
                <span>RESUME DETAIL</span>
                <span className="confidence"><FileText size={13} /> 简历详情</span>
              </div>
              <button
                ref={resumeCloseRef}
                className="icon-button"
                type="button"
                onClick={() => setActiveResume(null)}
                aria-label="关闭简历详情"
              >
                <X size={18} />
              </button>
            </header>

            <div className="drawer-body">
              <section className="student-profile">
                <div>
                  <h2 id="resume-detail-name">{resumeDisplayName(activeResume)}</h2>
                  <p>{PARSE_STATUS_LABEL[activeResume.parse_status] ?? activeResume.parse_status}</p>
                  <span>
                    {activeResume.email ? (
                      <>
                        <Mail size={13} /> {activeResume.email}
                      </>
                    ) : (
                      "暂无邮箱信息"
                    )}
                  </span>
                  {activeResume.phone ? (
                    <span>
                      <Phone size={13} /> {activeResume.phone}
                    </span>
                  ) : null}
                </div>
                <div className={`resume-badge status-${activeResume.parse_status}`}>
                  {PARSE_STATUS_LABEL[activeResume.parse_status] ?? activeResume.parse_status}
                </div>
              </section>

              <section className="drawer-section ai-summary">
                <div className="drawer-section-title"><Bot size={16} /><h3>AI 简历摘要</h3></div>
                <p>{activeResume.research_experience || "AI 摘要生成中，请稍后刷新查看"}</p>
              </section>

              <section className="drawer-section">
                <div className="drawer-section-title">
                  <Check size={16} />
                  <h3>技能标签</h3>
                </div>
                <div className="skill-chip-group">
                  {activeResume.skills ? (
                    activeResume.skills.split(/[,，、\s]+/).filter(Boolean).map((skill) => (
                      <span className="skill-chip matched" key={skill}>{skill}</span>
                    ))
                  ) : (
                    <p className="skill-chip-empty">暂无技能标签</p>
                  )}
                </div>
              </section>

              {activeResume.education ? (
                <section className="drawer-section">
                  <div className="drawer-section-title"><GraduationCap size={16} /><h3>教育背景</h3></div>
                  <p className="resume-excerpt">{activeResume.education}</p>
                </section>
              ) : null}

              {activeResume.status_note && activeResume.status_note !== "简历解析完成" ? (
                <section className="drawer-section risk-section">
                  <div className="drawer-section-title"><AlertTriangle size={16} /><h3>状态备注</h3></div>
                  <p>{activeResume.status_note}</p>
                </section>
              ) : null}
            </div>

            <footer className="drawer-footer three-actions">
              <button className="secondary-button" type="button" onClick={() => setActiveResume(null)}>
                关闭
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={isReparsing}
                onClick={() => reparseResume(activeResume)}
                title="重新调用 AI 解析该简历，用于修复解析失败或摘要生成异常的情况"
              >
                {isReparsing ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}
                重新解析
              </button>
              <button
                className="primary-button"
                type="button"
                disabled={isOpeningResumeFile}
                onClick={() => openStudentResumePdf(activeResume)}
              >
                {isOpeningResumeFile ? <LoaderCircle size={15} className="spin" /> : <ExternalLink size={15} />}
                查看原始简历
              </button>
            </footer>
          </aside>
        </div>
      ) : null}

      {adjustDrawerOpen ? (
        <div
          className="drawer-layer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !isRefining) setAdjustDrawerOpen(false);
          }}
        >
          <aside className="student-drawer adjust-drawer" role="dialog" aria-modal="true" aria-labelledby="adjust-drawer-title">
            <header className="drawer-header">
              <div className="drawer-code">
                <span>REFINE RESULTS</span>
                <span className="confidence"><Sparkles size={13} /> 调整结果</span>
              </div>
              <button
                ref={adjustCloseRef}
                className="icon-button"
                type="button"
                onClick={() => setAdjustDrawerOpen(false)}
                aria-label="关闭调整结果"
                disabled={isRefining}
              >
                <X size={18} />
              </button>
            </header>

            <div className="drawer-body">
              <h2 id="adjust-drawer-title" className="adjust-drawer-title">
                <Sparkles size={18} />
                告诉我们要怎么调整
              </h2>
              <div className="field adjust-field">
                <textarea
                  value={feedbackText}
                  onChange={(event) => setFeedbackText(event.target.value)}
                  placeholder="描述你想要的变化，例如：不再要求论文 / 优先有 PyTorch 项目经历的学生"
                  disabled={isRefining}
                  autoFocus
                />
              </div>
              {adjustmentNote ? (
                <div className="adjust-note" role="status">
                  <Sparkles size={14} />
                  <span>{adjustmentNote}</span>
                </div>
              ) : null}
            </div>

            <footer className="drawer-footer">
              <button
                className="secondary-button"
                type="button"
                onClick={() => setAdjustDrawerOpen(false)}
                disabled={isRefining}
              >
                取消
              </button>
              <button
                className="primary-button"
                type="button"
                onClick={submitFeedback}
                disabled={isRefining || !feedbackText.trim()}
              >
                {isRefining ? <LoaderCircle size={15} className="spin" /> : <Sparkles size={15} />}
                提交调整
              </button>
            </footer>
          </aside>
        </div>
      ) : null}

      {pdfPreview ? (
        <div
          className="pdf-preview-layer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closePdfPreview();
          }}
        >
          <div className="pdf-preview-modal" role="dialog" aria-modal="true" aria-labelledby="pdf-preview-title">
            <header className="pdf-preview-header">
              <h2 id="pdf-preview-title">
                <FileText size={16} /> {pdfPreview.title}
              </h2>
              <button
                ref={pdfPreviewCloseRef}
                className="icon-button"
                type="button"
                onClick={closePdfPreview}
                aria-label="关闭简历预览"
              >
                <X size={18} />
              </button>
            </header>
            <div className="pdf-preview-frame-wrap">
              {!pdfFrameLoaded ? (
                <div className="pdf-preview-loading" aria-hidden="true">
                  <LoaderCircle size={22} className="spin" />
                  <span>正在加载简历…</span>
                </div>
              ) : null}
              <iframe
                className={`pdf-preview-frame${pdfFrameLoaded ? " is-loaded" : ""}`}
                src={pdfPreview.url}
                title={pdfPreview.title}
                onLoad={() => setPdfFrameLoaded(true)}
              />
            </div>
          </div>
        </div>
      ) : null}

      {toast ? <div className="toast" role="status">{toast}</div> : null}
    </div>
  );
}
