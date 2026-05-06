from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _load_prompt(path: str | None, default_name: str) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return (Path(__file__).parent / "prompts" / default_name).read_text(encoding="utf-8")


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="summarizer",
        description="MAP-REDUCE summarizer for JSON/text files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    inp = p.add_argument_group("Input")
    inp.add_argument("--input", required=True, help="Path to input file")
    inp.add_argument("--format", choices=["json", "text"], default="json")
    inp.add_argument("--schema-hint", default="", help="Field descriptions (json format only)")

    task = p.add_argument_group("Task")
    task.add_argument("--prompt", required=True, help="Summarization goal/instructions")
    task.add_argument("--output-schema", default=None, help="Path to JSON Schema file (required for --output-mode json)")

    prompts = p.add_argument_group("Prompts (optional overrides)")
    prompts.add_argument("--map-prompt", default=None)
    prompts.add_argument("--reduce-prompt", default=None)
    prompts.add_argument("--compress-prompt", default=None)

    llm = p.add_argument_group("LLM")
    llm.add_argument("--model", default=os.getenv("LLM_MODEL", "default"))
    llm.add_argument("--api-base", default=os.getenv("LLM_API_BASE", "http://localhost:8000"))
    llm.add_argument("--api-key", default=os.getenv("LLM_API_KEY", "sk-placeholder"))

    out = p.add_argument_group("Output")
    out.add_argument("--output", "-o", default=None, help="Output file (default: stdout)")
    out.add_argument("--output-mode", choices=["json", "text"], default="json",
                     help="json: structured output with schema validation; text: free-form text")

    pipe = p.add_argument_group("Pipeline")
    pipe.add_argument("--map-concurrency", type=int, default=5)
    pipe.add_argument("--token-budget", type=int, default=6000)
    pipe.add_argument("--context-tokens", type=int, default=32000)
    pipe.add_argument("--max-reduce-rounds", type=int, default=20)

    return p.parse_args(argv)


async def _main(argv=None) -> int:
    args = _parse_args(argv)

    from summarizer.config import PipelineConfig
    from summarizer.loader import load
    from summarizer.pipeline import Pipeline

    if args.output_mode == "json":
        if not args.output_schema:
            print("ERROR: --output-schema is required for --output-mode json", file=sys.stderr)
            return 1
        try:
            output_schema = json.loads(Path(args.output_schema).read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"ERROR: output schema file not found: {args.output_schema}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid JSON in output schema: {e}", file=sys.stderr)
            return 1
    else:
        output_schema = {}

    try:
        map_prompt = _load_prompt(args.map_prompt, "map_default.txt")
        reduce_prompt = _load_prompt(args.reduce_prompt, "reduce_default.txt")
        compress_prompt = _load_prompt(args.compress_prompt, "compress_default.txt")
    except FileNotFoundError as e:
        print(f"ERROR: prompt file not found: {e}", file=sys.stderr)
        return 1

    config = PipelineConfig(
        input_path=args.input,
        format=args.format,
        schema_hint=args.schema_hint,
        user_prompt=args.prompt,
        output_schema=output_schema,
        map_prompt_template=map_prompt,
        reduce_prompt_template=reduce_prompt,
        compress_prompt_template=compress_prompt,
        model=args.model,
        api_base=args.api_base,
        api_key=args.api_key,
        output_path=args.output,
        output_mode=args.output_mode,
        map_concurrency=args.map_concurrency,
        token_budget=args.token_budget,
        context_tokens=args.context_tokens,
        max_reduce_rounds=args.max_reduce_rounds,
    )

    try:
        rows = load(args.input, args.format)
    except FileNotFoundError:
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not rows:
        print("ERROR: input file is empty", file=sys.stderr)
        return 1

    pipeline = Pipeline(config)
    result = await pipeline.run(rows)

    output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Result written to: {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
