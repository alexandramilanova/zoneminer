# ZoneMiner

ZoneMiner is a process mining tool for exploring how cases and tokens move through zones of a Petri net. Define zones, replay event logs, and investigate their behavior through interactive visualizations.

Developed at the Chair of Process and Data Science (PADS), RWTH Aachen University.

## Run ZoneMiner

The image supports ARM64 (including Apple Silicon) and AMD64 (Intel and AMD computers).
Install Docker, then run the image:

```sh
docker run --name zoneminer -p 127.0.0.1:7860:7860 -v zoneminer-data:/app/var alexandramilanova/zoneminer:latest
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860) and select **Load demo dataset**, or upload an uncompressed XES or CSV event log. You can also upload a PNML model. Stop the container with Ctrl+C and restart it with `docker start zoneminer`. The named volume preserves your data.

## Explore a process

- Select connected, disjoint groups of places as zones.
- Examine zone load, token replay, case journeys and changes over time.
- Investigate flow patterns and cross-zone associations.
- Run retrospective prediction experiments and compare their results with baselines.
- Export displayed charts and tables.

The included demo and example scenarios can be explored without obtaining external event logs. ZoneMiner has also been evaluated using five public-log case studies. External logs are not redistributed with the image.

Prediction is retrospective research functionality, and associations do not establish causality. Difficult alignments can require substantial time and memory.

## Source and screencast

The [source code and evaluation reports](https://github.com/alexandramilanova/zoneminer) are available on GitHub. Watch the [tool screencast](https://youtu.be/kXSjLgR6VUk).

## License

Application-authored code is licensed under MIT. Dependencies retain their respective licenses; PM4Py declares AGPL-3.0-or-later. See the license and third-party notices distributed with the application.
