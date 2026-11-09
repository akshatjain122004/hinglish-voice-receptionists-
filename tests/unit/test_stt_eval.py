from app.stt_eval import Sample, SampleResult, check_entities, load_manifest, render_report


class TestCheckEntities:
    def test_all_entities_present_passes(self):
        missing = check_entities(
            "Kal shaam saade paanch baje cleaning ka slot chahiye",
            {"day": ["kal"], "time": ["paanch"], "service": ["cleaning"]},
        )
        assert missing == []

    def test_missing_entity_is_reported_by_name(self):
        missing = check_entities(
            "Shaam saade paanch baje cleaning ka slot chahiye",
            {"day": ["kal"], "time": ["paanch"], "service": ["cleaning"]},
        )
        assert missing == ["day"]

    def test_case_insensitive(self):
        missing = check_entities("KAL SHAAM", {"day": ["kal"]})
        assert missing == []

    def test_any_alternate_satisfies_the_entity(self):
        """STT might transcribe a number as a digit or a spoken word —
        either should count, so entities list acceptable alternates."""
        missing = check_entities("5 baje cleaning", {"time": ["paanch", "5"]})
        assert missing == []


class TestLoadManifest:
    def test_parses_each_sample(self, tmp_path):
        manifest_path = tmp_path / "manifest.yaml"
        manifest_path.write_text(
            "- file: sample_01.wav\n"
            "  text: Kal shaam saade paanch baje cleaning ka slot chahiye.\n"
            "  entities:\n"
            "    day: [kal]\n"
            "    time: [paanch, '5']\n"
            "    service: [cleaning]\n",
            encoding="utf-8",
        )

        samples = load_manifest(manifest_path)

        assert samples == [
            Sample(
                file="sample_01.wav",
                text="Kal shaam saade paanch baje cleaning ka slot chahiye.",
                entities={"day": ["kal"], "time": ["paanch", "5"], "service": ["cleaning"]},
            )
        ]


class TestRenderReport:
    def test_counts_only_recorded_samples_in_the_pass_rate(self):
        results = [
            SampleResult(file="a.wav", status="pass", transcript="kal paanch cleaning"),
            SampleResult(
                file="b.wav", status="fail", transcript="paanch", missing_entities=["day"]
            ),
            SampleResult(file="c.wav", status="missing"),
        ]

        report = render_report(results)

        assert "1/2 recorded samples passed" in report
        assert "1 not yet recorded" in report

    def test_includes_each_file_and_its_missing_entities(self):
        results = [
            SampleResult(file="b.wav", status="fail", transcript="paanch", missing_entities=["day"])
        ]

        report = render_report(results)

        assert "b.wav" in report
        assert "day" in report
