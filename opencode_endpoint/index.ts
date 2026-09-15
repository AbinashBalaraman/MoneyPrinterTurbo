/**
 * OpenCode AI TypeScript / JavaScript SDK with Auto Models & Reasoning Fetch.
 * Compatible with Node.js 18+, Bun, Deno, and Browser/Vite.
 */

export type ReasoningEffort = 'xhigh' | 'high' | 'medium' | 'low' | 'off';

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  endpointType: 'responses' | 'chat-completions';
  supportedReasoning: ReasoningEffort[];
  defaultReasoning: ReasoningEffort;
  isFree: boolean;
  supportsVision: boolean;
  source: 'api' | 'builtin';
}

export interface OpenCodeClientOptions {
  apiKey?: string;
  baseUrl?: string;
  defaultModel?: string;
  defaultReasoning?: ReasoningEffort;
}

export class OpenCodeClient {
  public apiKey: string;
  public baseUrl: string;
  public defaultModel: string;
  public defaultReasoning: ReasoningEffort;
  private cachedModels: ModelInfo[] | null = null;

  constructor(options?: OpenCodeClientOptions) {
    const isBrowser = typeof window !== 'undefined';
    // No hardcoded fallback: a key compiled into the bundle is readable by
    // anyone who loads the page, and cannot be rotated. Set OPENCODE_API_KEY.
    const envApiKey =
      typeof process !== 'undefined' && process.env?.OPENCODE_API_KEY
        ? process.env.OPENCODE_API_KEY
        : '';

    this.apiKey = options?.apiKey || envApiKey;
    this.baseUrl = (
      options?.baseUrl ||
      (isBrowser ? '/api/opencode' : 'https://opencode.ai/zen/v1')
    ).replace(/\/$/, '');
    this.defaultModel = options?.defaultModel || 'muse-spark-1.3-contributor-free';
    this.defaultReasoning = options?.defaultReasoning || 'xhigh';
  }

  private buildHeaders(): Record<string, string> {
    const now = Date.now();
    return {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${this.apiKey}`,
      'x-opencode-session': `session-${now}`,
      'x-opencode-request': `req-${now}`,
      'x-opencode-client': 'vscode-copilot-chat',
      'User-Agent': 'opencode-copilot-chat/0.7.5 VSCode',
    };
  }

  /**
   * Auto-detects reasoning tiers and endpoint type for any model ID.
   */
  public getReasoningOptions(modelId?: string): {
    model: string;
    endpointType: 'responses' | 'chat-completions';
    supportedTiers: ReasoningEffort[];
    defaultTier: ReasoningEffort;
  } {
    const target = modelId || this.defaultModel;
    const lower = target.toLowerCase();

    let endpointType: 'responses' | 'chat-completions' = 'chat-completions';
    let supportedTiers: ReasoningEffort[] = ['high', 'medium', 'off'];
    let defaultTier: ReasoningEffort = 'off';

    if (lower.includes('muse-spark')) {
      endpointType = 'responses';
      supportedTiers = ['xhigh', 'high', 'medium', 'low', 'off'];
      defaultTier = 'xhigh';
    } else if (
      lower.includes('deepseek-v4') ||
      lower.includes('glm-5') ||
      lower.includes('mimo') ||
      lower.includes('qwen')
    ) {
      supportedTiers = ['high', 'medium', 'off'];
      defaultTier = 'high';
    } else if (lower.includes('nemotron') || lower.includes('ling')) {
      supportedTiers = ['off'];
      defaultTier = 'off';
    }

    return {
      model: target,
      endpointType,
      supportedTiers,
      defaultTier,
    };
  }

  /**
   * Auto-fetches live available models from OpenCode API.
   */
  public async listModels(options?: { onlyFree?: boolean; refresh?: boolean }): Promise<ModelInfo[]> {
    if (this.cachedModels && !options?.refresh) {
      return options?.onlyFree ? this.cachedModels.filter((m) => m.isFree) : this.cachedModels;
    }

    try {
      const res = await fetch(`${this.baseUrl}/models`, {
        method: 'GET',
        headers: this.buildHeaders(),
      });

      if (res.ok) {
        const data = await res.json();
        const rawList: any[] = data.data || [];
        this.cachedModels = rawList.map((item) => {
          const id: string = item.id || '';
          const reasoning = this.getReasoningOptions(id);
          return {
            id,
            name: id,
            endpointType: reasoning.endpointType,
            supportedReasoning: reasoning.supportedTiers,
            defaultReasoning: reasoning.defaultTier,
            isFree: id.toLowerCase().includes('free'),
            supportsVision: true,
            source: 'api',
          };
        });
      }
    } catch (err) {
      console.warn('Online models fetch failed, falling back to canonical models:', err);
    }

    // Fallback if online list failed
    if (!this.cachedModels || this.cachedModels.length === 0) {
      this.cachedModels = [
        {
          id: 'muse-spark-1.3-contributor-free',
          name: 'Muse Spark 1.3 (Free · Meta)',
          endpointType: 'responses',
          supportedReasoning: ['xhigh', 'high', 'medium', 'low', 'off'],
          defaultReasoning: 'xhigh',
          isFree: true,
          supportsVision: true,
          source: 'builtin',
        },
        {
          id: 'muse-spark-1.2-contributor-free',
          name: 'Muse Spark 1.2 (Free · Meta)',
          endpointType: 'responses',
          supportedReasoning: ['xhigh', 'high', 'medium', 'low', 'off'],
          defaultReasoning: 'xhigh',
          isFree: true,
          supportsVision: true,
          source: 'builtin',
        },
        {
          id: 'deepseek-v4-flash-free',
          name: 'DeepSeek v4 Flash (Free)',
          endpointType: 'chat-completions',
          supportedReasoning: ['high', 'medium', 'off'],
          defaultReasoning: 'high',
          isFree: true,
          supportsVision: true,
          source: 'builtin',
        },
        {
          id: 'mimo-v2.5-free',
          name: 'Mimo v2.5 (Free)',
          endpointType: 'chat-completions',
          supportedReasoning: ['high', 'medium', 'off'],
          defaultReasoning: 'high',
          isFree: true,
          supportsVision: true,
          source: 'builtin',
        },
      ];
    }

    return options?.onlyFree ? this.cachedModels.filter((m) => m.isFree) : this.cachedModels;
  }

  /**
   * Universal chat interface with auto reasoning and auto endpoint routing.
   */
  public async chat(
    promptOrMessages: string | ChatMessage[],
    options?: {
      model?: string;
      reasoningEffort?: ReasoningEffort;
      temperature?: number;
      systemPrompt?: string;
    }
  ): Promise<string> {
    const targetModel = options?.model || this.defaultModel;
    const reasoningInfo = this.getReasoningOptions(targetModel);
    const activeReasoning = options?.reasoningEffort || reasoningInfo.defaultTier;
    const isResponses = reasoningInfo.endpointType === 'responses';

    // Normalize messages
    let messages: ChatMessage[];
    if (typeof promptOrMessages === 'string') {
      messages = [];
      if (options?.systemPrompt) {
        messages.push({ role: 'system', content: options.systemPrompt });
      }
      messages.push({ role: 'user', content: promptOrMessages });
    } else {
      messages = [...promptOrMessages];
      if (options?.systemPrompt && !messages.some((m) => m.role === 'system')) {
        messages.unshift({ role: 'system', content: options.systemPrompt });
      }
    }

    let url: string;
    let payload: Record<string, any>;

    if (isResponses) {
      url = `${this.baseUrl}/responses`;
      payload = {
        model: targetModel,
        input: messages,
      };
      if (activeReasoning && activeReasoning !== 'off') {
        payload.reasoning = { effort: activeReasoning };
      }
    } else {
      url = `${this.baseUrl}/chat/completions`;
      payload = {
        model: targetModel,
        messages,
        temperature: options?.temperature ?? 0.7,
      };
      if (activeReasoning && activeReasoning !== 'off') {
        payload.reasoningEffort = activeReasoning;
      }
    }

    const res = await fetch(url, {
      method: 'POST',
      headers: this.buildHeaders(),
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`OpenCode API error (${res.status}): ${errText}`);
    }

    const data = await res.json();

    if (isResponses) {
      const messageItem = data.output?.find((item: any) => item.type === 'message');
      return messageItem?.content?.[0]?.text || '';
    } else {
      return data.choices?.[0]?.message?.content || '';
    }
  }
}
