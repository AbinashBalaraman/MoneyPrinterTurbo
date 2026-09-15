import argparse
import sys

try:
    from .client import OpenCodeClient
except ImportError:
    from client import OpenCodeClient


def main():
    parser = argparse.ArgumentParser(description="OpenCode AI Endpoint CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: models
    models_p = subparsers.add_parser("models", help="List all available models with reasoning tiers")
    models_p.add_argument("--free", action="store_true", help="Filter and display only free models")
    models_p.add_argument("--refresh", action="store_true", help="Force refresh models from online API")

    # Command: reasoning
    reasoning_p = subparsers.add_parser("reasoning", help="Auto-fetch reasoning options for a model")
    reasoning_p.add_argument("model", help="Model ID (e.g. muse-spark-1.3-contributor-free)")

    # Command: chat
    chat_p = subparsers.add_parser("chat", help="Send a prompt to OpenCode model")
    chat_p.add_argument("prompt", help="The text prompt to send")
    chat_p.add_argument("--model", "-m", default=None, help="Model ID (defaults to muse-spark-1.3-contributor-free)")
    chat_p.add_argument("--reasoning", "-r", default=None, help="Reasoning effort: xhigh, high, medium, low, off")
    chat_p.add_argument("--system", "-s", default=None, help="Optional system prompt")

    # Command: interactive
    subparsers.add_parser("interactive", help="Start an interactive multi-turn chat session")

    args = parser.parse_args()
    client = OpenCodeClient()

    if args.command == "models":
        print(f"\nFetching available models (Filter free: {args.free})...\n")
        models = client.list_models(only_free=args.free, refresh=args.refresh)
        print(f"{'MODEL ID':<36} | {'TYPE':<16} | {'DEFAULT REASON':<14} | {'FREE':<5} | {'SOURCE'}")
        print("-" * 85)
        for m in models:
            is_free_str = "YES" if m.is_free else "NO"
            print(f"{m.id:<36} | {m.endpoint_type:<16} | {m.default_reasoning:<14} | {is_free_str:<5} | {m.source}")
        print(f"\nTotal models: {len(models)}\n")

    elif args.command == "reasoning":
        info = client.get_reasoning_options(args.model)
        print("\nReasoning configuration for:", info["model"])
        print(f"  Endpoint Type:       {info['endpoint_type']}")
        print(f"  Recommended Default: {info['default_tier']}")
        print(f"  Supported Tiers:     {', '.join(info['supported_tiers'])}\n")

    elif args.command == "chat":
        print(f"\n[Sending prompt to {args.model or client.default_model}...]")
        resp = client.chat(
            prompt_or_messages=args.prompt,
            model=args.model,
            reasoning_effort=args.reasoning,
            system_prompt=args.system,
        )
        print("\n=== RESPONSE ===")
        print(resp)
        print("================")

    elif args.command == "interactive":
        print("\nStarting OpenCode Interactive Director Chat...")
        print("Type 'exit' or 'quit' to end. Type '/model <id>' to switch models.\n")
        history = []
        cur_model = client.default_model

        while True:
            try:
                user_input = input(f"User [{cur_model}]> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit"):
                    break
                if user_input.startswith("/model "):
                    cur_model = user_input.split(" ", 1)[1].strip()
                    print(f"Switched model to: {cur_model}")
                    continue

                history.append({"role": "user", "content": user_input})
                resp = client.chat(prompt_or_messages=history, model=cur_model)
                print(f"\nAssistant: {resp}\n")
                history.append({"role": "assistant", "content": resp})

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[Error]: {e}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
