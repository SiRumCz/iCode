import * as vscode from "vscode";

export const SECRET_API_KEY = "icode.apiKey";

export class IcodeConfig {
  constructor(
    readonly command: string,
    readonly args: string[],
    readonly env: Record<string, string>,
    readonly apiBase: string,
    readonly model: string,
    readonly provider: string,
    readonly home: string,
    readonly project: string,
    readonly autoApprove: boolean,
    readonly trace: boolean
  ) {}

  static fromWorkspace(): IcodeConfig {
    const cfg = vscode.workspace.getConfiguration("icode");
    const args = cfg.get<string[]>("args") ?? ["acp"];
    const autoApprove = cfg.get<boolean>("autoApprove") ?? false;
    const normalized = [...args];
    if (!normalized.includes("acp") && !normalized.some((a) => a.startsWith("acp"))) {
      normalized.unshift("acp");
    }
    if (autoApprove) {
      if (!normalized.includes("--auto-approve")) {
        normalized.push("--auto-approve");
      }
    } else if (!normalized.includes("--no-auto-approve")) {
      normalized.push("--no-auto-approve");
    }
    return new IcodeConfig(
      cfg.get<string>("command") ?? "icode",
      normalized,
      cfg.get<Record<string, string>>("env") ?? {},
      cfg.get<string>("apiBase") ?? "",
      cfg.get<string>("model") ?? "",
      cfg.get<string>("provider") ?? "",
      cfg.get<string>("home") ?? "",
      cfg.get<string>("project") ?? "",
      autoApprove,
      cfg.get<boolean>("trace") ?? false
    );
  }

  childEnv(apiKey: string): NodeJS.ProcessEnv {
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      ...this.env,
    };
    if (apiKey) {
      env.ICODE_API_KEY = apiKey;
      env.OPENJIUWEN_API_KEY = apiKey;
    }
    if (this.apiBase) {
      env.ICODE_API_BASE = this.apiBase;
      env.OPENJIUWEN_API_BASE = this.apiBase;
    }
    if (this.model) {
      env.ICODE_MODEL = this.model;
      env.OPENJIUWEN_MODEL = this.model;
    }
    if (this.provider) {
      env.ICODE_PROVIDER = this.provider;
      env.OPENJIUWEN_PROVIDER = this.provider;
    }
    if (this.home) {
      env.ICODE_HOME = this.home;
    }
    if (this.project) {
      env.ICODE_PROJECT = this.project;
    }
    return env;
  }
}
