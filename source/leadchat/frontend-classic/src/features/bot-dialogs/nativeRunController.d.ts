export interface NativeRunView {
  principal_id: string;
  run_id: string | null;
  operator_id: string | null;
  generation: number;
  state: "running" | "stopped" | "blocked";
  mode: "auto" | "rehearsal";
  auto_enabled: boolean;
  configured: boolean;
  worker_ready: boolean;
  start_available: boolean;
}

export interface StartTicket {
  readonly principal_id: string;
  readonly operator_id: string;
  readonly expected_generation: number;
  readonly observed_at: number;
}

export interface NativeRunState {
  view: NativeRunView | null;
  stale: boolean;
  lastConfirmedAt: number | null;
  error: string;
  busy: boolean;
  unknown: { operation: "start" | "stop"; principal_id: string; expected_generation: number } | null;
}

export interface NativeRunController {
  state: NativeRunState;
  inspect(): Promise<NativeRunView | null>;
  prepareStart(): Promise<StartTicket>;
  start(ticket: StartTicket): Promise<NativeRunView | null>;
  stop(): Promise<NativeRunView | null>;
  watch(): void;
  unwatch(): void;
}

export function createRun(deps: {
  get(path: string): Promise<unknown>;
  post(path: string, body: unknown): Promise<unknown>;
  identity(): Promise<{ id: string; role: string }>;
  principal(): string;
  operator(): string;
  onChange(state: NativeRunState): void;
}): NativeRunController;
