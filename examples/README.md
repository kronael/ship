# demiurg examples

example design files demonstrating demiurg usage.

## usage

```bash
# run an example
demiurg examples/hello-world.txt

# or copy and modify
cp examples/fastapi-server.txt my-design.txt
# edit my-design.txt
demiurg my-design.txt
```

## examples

### hello-world.txt
minimal example: creates a simple hello world script.

### fastapi-server.txt
builds a complete FastAPI REST API with:
- health check endpoint
- CRUD endpoints with validation
- pagination support
- pytest tests
- OpenAPI docs

### cli-tool.txt
creates a CLI tool using click:
- multiple subcommands
- config file management
- command-line flags
- tests for all commands

## writing your own

design files are plain text with tasks as bullet points:

```
- Create foo.py module
- Add function bar() that does X
- Write tests for bar()
- Add error handling for edge case Y
```

tips:
- one task per line (bullet points)
- be specific and actionable
- start with verbs (create, add, write, implement)
- mention files/modules explicitly
- tasks run in parallel, so order doesn't matter for independent work
