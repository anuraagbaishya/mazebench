# Costs

OpenRouter billed cost (`usage.cost`) summed over the result files in this folder. A blank cell means the model did not run that task. Rows are sorted by total spend.

| Model | Mazes described | Describe | Solve run 1 | Solve run 2 |
|---|---:|---:|---:|---:|
| `anthropic/claude-sonnet-5.5` | 100 | $2.06 | $2.65 | $2.78 |
| `qwen/qwen3.8-max-0902` | 100 | $6.95 |  |  |
| `google/gemini-4-argon` | 100 | $1.02 | $3.09 | $2.64 |
| `meta/muse-spark-1.3` | 20 | $2.65 |  |  |
| `google/gemini-3.8-flash` | 20 | $2.26 |  |  |
| `mistralai/mistral-large-4-0` | 20 | $1.33 |  |  |
| `openai/gpt-6-luna` | 100 | $0.22 | $0.45 | $0.44 |
| `anthropic/claude-haiku-5.5` | 100 | $0.21 | $0.25 | $0.29 |
| `deepseek/deepseek-v4.1-flash` | 20 | $0.65 |  |  |
| `xiaomi/mimo-v2.6-pro` | 20 | $0.18 |  |  |
| `nvidia/nemotron-3.5-super-vl` | 20 | $0.16 |  |  |
| `z-ai/glm-5.3-flash` (low effort) | 20 | $0.07 |  |  |
| `minimax/minimax-m3.1-flash:free` | 20 | $0.00 |  |  |
| **Total** |  | **$17.76** | **$6.44** | **$6.15** |

The files in this folder cost $30.34 in total.

## What the columns cover

- **Describe:** the cost of the description run in `<model>.describe.json`. Five models described all 100 mazes; the others described the first 20.
- **Solve:** the cost of one full pass over the 100 mazes, from `<model>.image.run1.json` and `run2.json`. Only the four models listed ran the solving task.
- **Free tier:** `minimax/minimax-m3.1-flash:free` ran on OpenRouter's free tier, so it cost $0.00.
- **Imported results:** `anthropic_claude-sonnet-5.5.describe.imported.*.json` was produced outside this repo's API pipeline, has no usage data and is not counted.
- **Not included:** requests that failed or were abandoned (for example a stalled run) are billed but not saved in any result file, so the bill for a project like this is somewhat higher than the sum above.
