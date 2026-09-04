"""CodeZip entrypoint for Amazon Bedrock AgentCore Runtime.

AgentCore starts this file with ``opentelemetry-instrument main.py`` (the CLI's CDK sets that
entry point whenever ``instrumentation.enableOtel`` is true), so the ADOT auto-instrumentation
is already wrapped around the process by the time anything here runs. All this module does is
import the real app — :mod:`porchlight.runtime` — and serve it on port 8080.

``porchlight/`` itself is not a PyPI package, so ``make package-runtime`` rsyncs the repo's
package into ``runtime/porchlight/`` (gitignored) just before ``agentcore package`` /
``agentcore deploy`` zips this directory. See ``docs/DEPLOY.md`` § AgentCore Runtime.
"""

from porchlight.runtime import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    main()
