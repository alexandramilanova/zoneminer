# Hugging Face Docker setup

ZoneMiner runs on CPU hardware. Start with a private Docker Space and test it
before making it accessible to reviewers. The local Docker installation remains
the fallback for workloads that exceed the host's memory or acceptable latency.

1. Create a Docker/Blank Space under the account that will maintain the service.
   Check the current [plan requirements](https://huggingface.co/pricing) and
   [hardware resources](https://huggingface.co/docs/hub/spaces-overview).
2. Copy the reviewed source, Dockerfile and dependency locks into the Space
   repository. Exclude `.git`, virtual environments, local runtime data and
   credentials. Keep the license and third-party notices.
3. Keep the supplied README front matter, which configures the Docker SDK and
   application port:

   ```yaml
   ---
   title: ZoneMiner
   sdk: docker
   app_port: 7860
   ---
   ```

4. Configure these runtime variables:

   ```text
   ZONE_ANALYTICS_MODE=anonymous
   ZONE_ANALYTICS_COOKIE_SECURE=1
   ZONE_ANALYTICS_DATA_DIR=/app/var
   ZONE_ANALYTICS_NATIVE_THREADS=1
   ```

   Use one replica and one API process. Leave memory budgeting automatic unless
   measurements justify overriding it. File-size, event-count and computation
   caps are optional; see [anonymous workspaces](anonymous-workspaces.md).
5. Test the direct HTTPS `.hf.space` URL: uploads, analysis, downloads, separate
   visitor sessions, deletion, expiry, waking from sleep and restart. Local
   Docker verification does not verify the provider's proxy or cookie behaviour.
6. Complete the [dependency/source-distribution review](dependency-review.md)
   before public access. A private Space is accessible only to its collaborators;
   an anonymous conference reviewer needs a deliberately accessible release.
7. Record the tested source revision and image digest, and provide a matching
   downloadable source release for local installation. A private repository URL
   alone does not provide anonymous download access.

Runtime storage is temporary and may be lost when the Space stops or restarts.
Users should download results they want to retain. Sleeping does not change the
application's features, but waking requires startup time. Jobs do not resume
automatically after process restart.

Provider documentation: [Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker),
[hardware and sleeping](https://huggingface.co/docs/hub/spaces-gpus),
[storage](https://huggingface.co/docs/hub/spaces-storage).
