/**
 * harness-sdk TypeScript 类型定义
 *
 * 与 Python SDK 的 harness.types 对齐，确保跨语言类型一致。
 * 所有枚举和 dataclass 用 TypeScript enum + interface 对应。
 */

// ─── Agent ────────────────────────────────────────────

export enum AgentCapability {
  PERCEIVE = 'perceive',
  REASON = 'reason',
  EXECUTE = 'execute',
  REMEMBER = 'remember',
  COLLABORATE = 'collaborate',
  SELF_DRIVE = 'self_drive',
}

export enum AgentType {
  CODER = 'coder',
  REVIEWER = 'reviewer',
  ARCHITECT = 'architect',
  TESTER = 'tester',
  ORCHESTRATOR = 'orchestrator',
}

export enum TaskStatus {
  /** 任务成功完成 */
  Completed = 'completed',
  /** 任务执行失败 */
  Failed = 'failed',
  /** 任务升级到人工处理 */
  Escalated = 'escalated',
}

export interface AgentDefinition {
  id: string;
  name: string;
  capabilities: AgentCapability[];
  toolsets: string[];
  agentType?: AgentType;
  maxRounds: number;
  temperature: number;
  systemPrompt: string;
  metadata: Record<string, unknown>;
}

export interface TaskResult {
  taskId: string;
  agentId: string;
  /** 任务状态——推荐使用 TaskStatus enum，但字符串 'completed'|'failed'|'escalated' 仍向后兼容 */
  status: TaskStatus | 'completed' | 'failed' | 'escalated';
  artifacts: Artifact[];
  durationMs: number;
  tokensUsed: number;
  error?: string;
  metadata: Record<string, unknown>;
}

export interface Artifact {
  type: 'code' | 'doc' | 'config' | 'test' | 'log';
  path: string;
  content: string;
  metadata: Record<string, unknown>;
}

// ─── Gate ──────────────────────────────────────────────

export enum GateMode {
  STRICT = 'strict',
  HYBRID = 'hybrid',
  LOOSE = 'loose',
}

export interface GateCheck {
  id: string;
  category: 'security' | 'privacy' | 'compliance' | 'style' | 'logic';
  severity: 'critical' | 'high' | 'medium' | 'low';
  checkFn: (artifact: Artifact) => CheckResult;
}

export interface CheckResult {
  passed: boolean;
  severity: string;
  message: string;
  autoFixable: boolean;
  fixSuggestion?: string;
}

export interface RetryStrategy {
  maxRetries: number;
  backoffMs: number;
  depthReduction: boolean;
  escalationThreshold: number;
}

// ─── Compliance ────────────────────────────────────────

export enum ComplianceCategory {
  SECURITY = 'security',
  PRIVACY = 'privacy',
  LICENSE = 'license',
  LEGAL = 'legal',
  STYLE = 'style',
  ARCHITECTURE = 'architecture',
}

export interface ComplianceRule {
  id: string;
  category: ComplianceCategory;
  pattern: string;
  severity: string;
  description: string;
  remediation: string;
  autoFixable: boolean;
}

export interface ComplianceResult {
  ruleId: string;
  passed: boolean;
  severity: string;
  findings: string[];
  remediation?: string;
}

// ─── Guardrails ────────────────────────────────────────

export enum GuardrailAction {
  BLOCK = 'block',
  WARN = 'warn',
  REDACT = 'redact',
  REPLACE = 'replace',
}

export interface InputGuardrailConfig {
  detectPiiTypes: string[];
  piiAction: GuardrailAction;
  maxInputLength: number;
  bannedPhrases: string[];
  longPromptThreshold: number;
}

export interface OutputGuardrailConfig {
  detectPiiInOutput: boolean;
  outputPiiAction: GuardrailAction;
  bannedOutputPatterns: string[];
  maxOutputLength: number;
  checkCodeSafety: boolean;
}

// ─── Constraints ────────────────────────────────────────

export interface AgentConstraints {
  filePatterns: string[];
  maxChanges: number;
  requireReview: boolean;
  noDestructive: boolean;
  timeout: number;
  priority: AgentPriority;
  allowedCommands: string[];
  maxTokens: number;
}

export enum AgentPriority {
  LOW = 'low',
  NORMAL = 'normal',
  HIGH = 'high',
  CRITICAL = 'critical',
}

// ─── DAG ────────────────────────────────────────────────

export interface DAGNode {
  id: string;
  agentType: string;
  task: string;
  inputs: string[];
  outputs: string[];
  gate?: GateCheck;
}

export interface DAGEdge {
  fromNode: string;
  toNode: string;
  condition?: string;
}

export interface DAGWorkflow {
  id: string;
  nodes: DAGNode[];
  edges: DAGEdge[];
  entryNode: string;
}

// ─── Scheduler ────────────────────────────────────────

export interface SchedulePlan {
  parallelGroups: string[][];
  criticalPath: string[];
  checkpoints: string[];
  estimatedDurationMs: number;
  estimatedTokens: number;
}

export interface ResourceUsage {
  tokensUsed: number;
  rpmUsed: number;
  currentParallelism: number;
}

export interface SmartSchedulerConfig {
  maxParallelism: number;
  llmRateLimitPerMinute: number;
  tokenBudget: number;
  retryStrategy: string;
  mergeThreshold: number;
}

// ─── Negotiation ────────────────────────────────────────

export enum NegotiationEventType {
  CONFLICT_ALERT = 'conflict_alert',
  REVIEW_REQUEST = 'review_request',
  DEBATE_PROPOSAL = 'debate_proposal',
  DEBATE_RESULT = 'debate_result',
  ESCALATION = 'escalation',
}

export interface NegotiationEvent {
  id: string;
  timestamp: string;
  eventType: NegotiationEventType;
  payload: Record<string, unknown>;
}

export interface FileConflict {
  filePath: string;
  agentA: string;
  agentB: string;
  rangesA: Record<string, unknown>[];
  rangesB: Record<string, unknown>[];
  contentA: string;
  contentB: string;
}

// ─── Audit ──────────────────────────────────────────────

export interface AuditEntry {
  timestamp: string;
  task: string;
  sessionId: string;
  decisions: Record<string, unknown>[];
  actions: Record<string, unknown>[];
  outcomes: Record<string, unknown>;
  riskAssessment?: Record<string, unknown>;
}

export interface AuditStats {
  totalTasks: number;
  delivered: number;
  autoFixed: number;
  escalated: number;
  verificationPassRate: number;
}

// ─── Learning ────────────────────────────────────────────

export interface ExecutionTrace {
  workflowId: string;
  timestamp: string;
  durationMs: number;
  nodes: TraceNode[];
  finalStatus: string;
}

export interface TraceNode {
  nodeId: string;
  agentType: string;
  task: string;
  resultStatus: string;
  durationMs: number;
  tokensUsed: number;
  retries: number;
  gatePassed: boolean;
  filesModified: string[];
  filesRead: string[];
}

export interface Recommendation {
  type: string;
  confidence: number;
  description: string;
  suggestedAction: string;
  evidence?: string[];
}

// ─── Bus ────────────────────────────────────────────────

export enum BusEventType {
  NODE_START = 'node:start',
  NODE_COMPLETE = 'node:complete',
  NODE_FAIL = 'node:fail',
  GATE_CHECK = 'gate:check',
  GATE_PASS = 'gate:pass',
  GATE_RETRY = 'gate:retry',
  PIPELINE_COMPLETE = 'pipeline:complete',
  PIPELINE_FAIL = 'pipeline:fail',
  CONFLICT_ALERT = 'conflict:alert',
  ESCALATION = 'escalation',
  AGENT_REGISTERED = 'agent:registered',
  TRACE_CAPTURED = 'trace:captured',
  RECOMMENDATION = 'recommendation',
}

export interface BusEvent {
  type: BusEventType;
  executionId: string;
  nodeId?: string;
  agentId?: string;
  data?: Record<string, unknown>;
}

// ─── Knowledge ──────────────────────────────────────────

export enum KnowledgeType {
  ARCHITECTURE = 'architecture',
  CONVENTION = 'convention',
  DEPENDENCY = 'dependency',
  API = 'api',
  PATTERN = 'pattern',
  RISK = 'risk',
  DECISION = 'decision',
  TASK = 'task',
  TEST = 'test',
  GLOSSARY = 'glossary',
}

export enum KnowledgeScope {
  PROJECT = 'project',
  MODULE = 'module',
  FILE = 'file',
  FUNCTION = 'function',
}

export interface KnowledgeEntry {
  id: string;
  type: KnowledgeType;
  scope: KnowledgeScope;
  title: string;
  content: string;
  metadata: Record<string, unknown>;
  tags: string[];
  confidence: number;
  source?: string;
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeQuery {
  query: string;
  typeFilter?: KnowledgeType;
  scopeFilter?: KnowledgeScope;
  tagsFilter?: string[];
  sourceFilter?: string;
  limit: number;
}

export interface KnowledgeQueryResult {
  entries: KnowledgeEntry[];
  totalMatches: number;
  query: string;
  searchMethod: string;
}

// ─── Hook (SDK) ────────────────────────────────────────

export enum HookType {
  BEFORE = 'before',
  AFTER = 'after',
  ON_ERROR = 'on_error',
}

export interface HookContext {
  task: string;
  agentName: string;
  agentId: string;
  context: Record<string, unknown>;
  result?: TaskResult;
  error?: string;
  hookType: HookType;
  metadata: Record<string, unknown>;
}

export enum HookResult {
  CONTINUE = 'continue',
  SKIP = 'skip',
  ABORT = 'abort',
}

// ─── Harness Config ────────────────────────────────────

export interface HarnessConfig {
  projectName: string;
  projectPath: string;
  logLevel: string;
  auditStoreDir: string;
  scheduler: SmartSchedulerConfig;
  defaultGateMode: GateMode;
  compliancePacks: string[];
  learningEnabled: boolean;
  learningInterval: number;
  escalationHandler: string;
  escalationTimeoutMs: number;
}