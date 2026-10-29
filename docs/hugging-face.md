# Hugging Face deployment

## Current stage

ZoneMiner is deployed in the private
[`alexandramilanova/zoneminer` Space](https://huggingface.co/spaces/alexandramilanova/zoneminer).
Open the [direct application URL](https://alexandramilanova-zoneminer.hf.space)
in its own browser tab for uploads and analysis. The embedded Hugging Face view
can be affected by browser restrictions on third-party session cookies.

The current deployment stage was checked on 29 October 2026. The Space's
[commit history](https://huggingface.co/spaces/alexandramilanova/zoneminer/commits/main)
identifies each deployed update.
Public access and a reviewer-accessible source download remain separate release
decisions; the private Space and repository do not provide anonymous access.

## Computing limitations and recommended local use

The hosted application uses shared, finite CPU, RAM and temporary storage. It
runs one API process and one isolated computation at a time; other admitted
computations wait. Browser API requests are queued to reduce admission bursts,
but session, job and resource safeguards still apply. There is no default fixed
log-size or event-count cap. Large or complex inputs can still exhaust available
memory, take impractically long or outlive their temporary session.

**Use the local Docker or source installation for full performance**, especially
for large logs and repeated or compute-intensive experiments. The same analysis
features are available locally, with a persistent workspace and the resources
of your own machine. Local installation does not guarantee unlimited capacity.
See the [local quickstart](../README.md#quickstart) and
[runtime resource boundaries](anonymous-workspaces.md#resource-boundaries).

## Configuration and updates

The following settings describe the Docker deployment. Keep the Space private
until the release access and dependency/source-distribution decisions are complete.

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
   ZONE_ANALYTICS_PUBLIC_ORIGIN=https://YOUR-SPACE-SUBDOMAIN.hf.space
   ```

   Set `PUBLIC_ORIGIN` to the exact HTTPS origin of the running app (from the
   Space's direct URL), without a path. For `alexandramilanova/zoneminer`, use
   `https://alexandramilanova-zoneminer.hf.space`. This preserves the browser-origin
   check when the hosting proxy uses a different internal host or scheme. Do not
   use the `huggingface.co/spaces/...` page URL or a wildcard.

   Use one replica and one API process. Leave memory budgeting automatic unless
   measurements justify overriding it. File-size, event-count and computation
   caps are optional; see [anonymous workspaces](anonymous-workspaces.md).
5. Test the direct HTTPS `.hf.space` URL after each application update: uploads, analysis, downloads, separate
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

Push reviewed changes to the Space repository to trigger a Docker rebuild.
Rebuilds can interrupt active jobs and discard temporary data; finish current
experiments and download results first. Once the Space reports Running, reload
the direct application tab and check loading, zone validation and analysis.

Provider documentation: [Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker),
[hardware and sleeping](https://huggingface.co/docs/hub/spaces-gpus),
[storage](https://huggingface.co/docs/hub/spaces-storage).
