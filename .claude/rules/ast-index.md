# ast-index Rules

## Mandatory Search Rules

1. **ALWAYS use ast-index FIRST** for any code search task
2. **NEVER duplicate results** — if ast-index found usages/implementations, that IS the complete answer
3. **DO NOT run grep "for completeness"** after ast-index returns results
4. **Use grep/Search ONLY when:**
   - ast-index returns empty results
   - Searching for regex patterns (ast-index uses literal match)
   - Searching for string literals inside code (`"some text"`)
   - Searching in comments content

## Why ast-index

ast-index is 17-69x faster than grep (1-10ms vs 200ms-3s) and returns structured, accurate results.

## Command Reference

| Task | Command | Time |
|------|---------|------|
| Universal search | `ast-index search "query"` | ~10ms |
| Find class | `ast-index class "ClassName"` | ~1ms |
| Find symbol | `ast-index symbol "symbol_name"` | ~1ms |
| Find usages | `ast-index usages "symbol_name"` | ~8ms |
| Find implementations | `ast-index implementations "BaseClass"` | ~5ms |
| Call hierarchy | `ast-index call-tree "function" --depth 3` | ~1s |
| Find callers | `ast-index callers "function_name"` | ~1s |
| Module deps | `ast-index deps "module_name"` | ~10ms |
| File outline | `ast-index outline "file.py"` | ~1ms |

## Python-Specific Commands

| Task | Command |
|------|---------|
| Find class | `ast-index class "MyClass"` |
| Find function | `ast-index symbol "my_function"` |
| Find decorator usage | `ast-index search "@router"` |
| Find dataclass | `ast-index class "Schema"` |
| Find async functions | `ast-index search "async def"` |
| Find Pydantic models | `ast-index class "BaseModel"` |
| Find FastAPI routes | `ast-index search "@app."` |

## Index Management

- `ast-index rebuild` — Full reindex (run once after clone)
- `ast-index update` — After git pull/merge
- `ast-index stats` — Show index statistics
