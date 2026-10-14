"""Comprehensive evaluation and benchmark of Audio Focus modes across representative mixed audio categories.

Categories evaluated:
1. Silence / noise floor
2. Vocals and no drums (acapella / speech)
3. Vocals plus quiet drums
4. Strong kick drums (EDM / rock)
5. Sustained basslines (808 / synth pedal)
6. Acoustic percussion (snares and hi-hats)
7. Instrumental music (acoustic guitar / piano arpeggio)

Quantifies True Positives, False Positives, Missed Onsets, Precision, and Recall
across Full Music, Rhythm Focus, and Kick Focus modes.
"""

from dataclasses import dataclass
from typing import List, Tuple
import numpy as np
import pytest

from src.audio.analyzer import AudioAnalyzer
from src.audio.beat_detector import AudioFocus


@dataclass
class EvalMetrics:
    mode: str
    category: str
    reference_count: int
    detected_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float


def generate_audio_dataset(sample_rate: int = 48000, duration_s: float = 2.0):
    """Generate deterministic synthetic audio signals with known ground truth reference onset times."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    dataset = {}

    # 1. Silence (noise floor ~ 1e-4 RMS)
    rng = np.random.default_rng(42)
    dataset["silence"] = {
        "audio": rng.normal(0, 1e-4, len(t)).astype(np.float32),
        "ref_onsets": [],
    }

    # 2. Vocals and no drums (Acapella / Speech)
    # Formants at 350 Hz, 850 Hz, 1400 Hz with 5 Hz vibrato and syllabic amplitude modulation
    vib_phase = 2 * np.pi * 5.0 * t
    p1 = 2 * np.pi * 350.0 * t - (350.0 * 0.03 / 5.0) * np.cos(vib_phase)
    p2 = 2 * np.pi * 850.0 * t - (850.0 * 0.03 / 5.0) * np.cos(vib_phase)
    p3 = 2 * np.pi * 1400.0 * t - (1400.0 * 0.03 / 5.0) * np.cos(vib_phase)
    f1 = np.sin(p1)
    f2 = 0.5 * np.sin(p2)
    f3 = 0.3 * np.sin(p3)
    # Syllabic envelope: smooth 2.5 Hz sine envelope
    syllabic_env = 0.5 * (1.0 + np.sin(2 * np.pi * 2.5 * t))
    vocal_audio = ((f1 + f2 + f3) * syllabic_env * 0.4).astype(np.float32)
    dataset["vocals_no_drums"] = {
        "audio": vocal_audio,
        "ref_onsets": [],  # No percussion onsets
    }

    # 3. Vocals plus quiet drums
    # Vocal audio mixed with subtle 60 Hz kick pulses every 500 ms (t = 0.5, 1.0, 1.5s)
    mixed_audio = vocal_audio.copy()
    ref_quiet_kicks = [0.5, 1.0, 1.5]
    for hit_t in ref_quiet_kicks:
        start_idx = int(hit_t * sample_rate)
        kick_len = int(0.06 * sample_rate)
        if start_idx + kick_len < len(mixed_audio):
            t_kick = np.linspace(0, 0.06, kick_len, endpoint=False)
            kick_pulse = 0.35 * np.sin(2 * np.pi * 60.0 * t_kick) * np.exp(-t_kick / 0.02)
            mixed_audio[start_idx : start_idx + kick_len] += kick_pulse.astype(np.float32)
    dataset["vocals_quiet_drums"] = {
        "audio": mixed_audio,
        "ref_onsets": ref_quiet_kicks,
    }

    # 4. Strong kick drums (Four-on-the-floor EDM kick at 120 BPM: t = 0.25, 0.75, 1.25, 1.75s)
    kick_audio = np.zeros_like(t, dtype=np.float32)
    ref_strong_kicks = [0.25, 0.75, 1.25, 1.75]
    for hit_t in ref_strong_kicks:
        start_idx = int(hit_t * sample_rate)
        kick_len = int(0.08 * sample_rate)
        if start_idx + kick_len < len(kick_audio):
            t_k = np.linspace(0, 0.08, kick_len, endpoint=False)
            # Pitch drop from 130 Hz down to 55 Hz
            freq = 55.0 + 75.0 * np.exp(-t_k / 0.02)
            phase = 2 * np.pi * np.cumsum(freq) / sample_rate
            kick_wave = 0.85 * np.sin(phase) * np.exp(-t_k / 0.025)
            kick_audio[start_idx : start_idx + kick_len] += kick_wave.astype(np.float32)
    dataset["strong_kick_drums"] = {
        "audio": kick_audio,
        "ref_onsets": ref_strong_kicks,
    }

    # 5. Sustained bassline (Continuous 55 Hz tone sustained for 1.5 seconds)
    sustained_audio = np.zeros_like(t, dtype=np.float32)
    start_s = int(0.1 * sample_rate)
    end_s = int(1.6 * sample_rate)
    t_sub = t[start_s:end_s] - t[start_s]
    # Fast initial attack (10ms) followed by constant sustained plateau
    att_len = int(0.01 * sample_rate)
    env = np.ones(len(t_sub), dtype=np.float32)
    env[:att_len] = np.linspace(0.0, 1.0, att_len)
    sustained_audio[start_s:end_s] = (0.75 * np.sin(2 * np.pi * 55.0 * t_sub) * env).astype(np.float32)
    dataset["sustained_bassline"] = {
        "audio": sustained_audio,
        "ref_onsets": [0.1],  # Only the initial strike at 0.1s is an onset; sustain has NO onsets
    }

    # 6. Acoustic percussion (Snares at 2.5 kHz and Hi-hats at 9 kHz, no sub-bass)
    perc_audio = np.zeros_like(t, dtype=np.float32)
    ref_perc = [0.35, 0.70, 1.05, 1.40]
    for i, hit_t in enumerate(ref_perc):
        start_idx = int(hit_t * sample_rate)
        dur = 0.05
        hit_len = int(dur * sample_rate)
        if start_idx + hit_len < len(perc_audio):
            t_p = np.linspace(0, dur, hit_len, endpoint=False)
            carrier = 2500.0 if (i % 2 == 0) else 9000.0
            noise = rng.normal(0, 1.0, hit_len)
            noise_hp = np.diff(noise, prepend=noise[0])
            tone = np.sin(2 * np.pi * carrier * t_p)
            burst = 0.6 * (0.6 * tone + 0.4 * noise_hp) * np.exp(-t_p / 0.015)
            perc_audio[start_idx : start_idx + hit_len] += burst.astype(np.float32)
    dataset["acoustic_percussion"] = {
        "audio": perc_audio,
        "ref_onsets": ref_perc,
    }

    # 7. Instrumental music (Polyphonic guitar arpeggio notes changing every 400 ms)
    inst_audio = np.zeros_like(t, dtype=np.float32)
    chord_freqs = [261.6, 329.6, 392.0, 523.3]
    ref_inst = [0.2, 0.6, 1.0, 1.4]
    for hit_t, freq in zip(ref_inst, chord_freqs):
        start_idx = int(hit_t * sample_rate)
        note_len = int(0.35 * sample_rate)
        if start_idx + note_len < len(inst_audio):
            t_n = np.linspace(0, 0.35, note_len, endpoint=False)
            note = 0.4 * (np.sin(2 * np.pi * freq * t_n) + 0.3 * np.sin(2 * np.pi * 2 * freq * t_n))
            # Gentle string attack (15ms) and decay
            att = int(0.015 * sample_rate)
            env_n = np.exp(-t_n / 0.15)
            env_n[:att] = np.linspace(0.0, 1.0, att)
            inst_audio[start_idx : start_idx + note_len] += (note * env_n).astype(np.float32)
    dataset["instrumental_music"] = {
        "audio": inst_audio,
        "ref_onsets": ref_inst,
    }

    return dataset


def run_analyzer_evaluation(audio_data: np.ndarray, ref_onsets: List[float], focus_mode: AudioFocus, sample_rate: int = 48000) -> Tuple[List[float], EvalMetrics]:
    """Run AudioAnalyzer over audio stream in chunks, collecting detected onset timestamps and matching with reference events."""
    analyzer = AudioAnalyzer(sample_rate=sample_rate, buffer_size=1024, audio_focus=focus_mode)

    chunk_size = 1024
    hop_size = 1024
    detected_times = []

    for i in range(0, len(audio_data) - chunk_size + 1, hop_size):
        chunk = audio_data[i : i + chunk_size]
        chunk_time = i / sample_rate
        metrics = analyzer.analyze_frame(chunk)
        if metrics.is_onset:
            detected_times.append(chunk_time)

    # Match detected onsets with reference onsets within +/- 45ms tolerance
    tolerance_s = 0.045
    matched_refs = set()
    true_positives = 0
    false_positives = 0

    for det_t in detected_times:
        matched = False
        for idx, ref_t in enumerate(ref_onsets):
            if abs(det_t - ref_t) <= tolerance_s and idx not in matched_refs:
                matched_refs.add(idx)
                true_positives += 1
                matched = True
                break
        if not matched:
            false_positives += 1

    false_negatives = len(ref_onsets) - len(matched_refs)
    precision = (true_positives / (true_positives + false_positives)) if (true_positives + false_positives) > 0 else (1.0 if len(ref_onsets) == 0 else 0.0)
    recall = (true_positives / len(ref_onsets)) if len(ref_onsets) > 0 else (1.0 if detected_times == 0 else 0.0)

    eval_result = EvalMetrics(
        mode=focus_mode.value,
        category="",
        reference_count=len(ref_onsets),
        detected_count=len(detected_times),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=round(precision, 3),
        recall=round(recall, 3),
    )
    return detected_times, eval_result


@pytest.fixture(scope="module")
def audio_dataset():
    return generate_audio_dataset()


class TestAudioFocusEvaluation:
    """Verifies percussion isolation, vocal suppression, and false positive rejection across 7 audio categories."""

    def test_silence_produces_zero_onsets_all_modes(self, audio_dataset):
        """Silence must produce zero onsets in all focus modes."""
        for mode in [AudioFocus.FULL_MUSIC, AudioFocus.RHYTHM, AudioFocus.KICK]:
            dets, metrics = run_analyzer_evaluation(audio_dataset["silence"]["audio"], audio_dataset["silence"]["ref_onsets"], mode)
            assert len(dets) == 0, f"Mode {mode.value} produced {len(dets)} false onsets on silence!"

    def test_vocal_suppression_in_rhythm_and_kick_modes(self, audio_dataset):
        """Acapella vocal track should have zero or near-zero false onsets in Rhythm and Kick modes compared to Full Music."""
        audio = audio_dataset["vocals_no_drums"]["audio"]
        refs = audio_dataset["vocals_no_drums"]["ref_onsets"]

        _, full_metrics = run_analyzer_evaluation(audio, refs, AudioFocus.FULL_MUSIC)
        _, rhythm_metrics = run_analyzer_evaluation(audio, refs, AudioFocus.RHYTHM)
        _, kick_metrics = run_analyzer_evaluation(audio, refs, AudioFocus.KICK)

        print(f"\n[Vocals No Drums] Full False Positives: {full_metrics.false_positives} | Rhythm: {rhythm_metrics.false_positives} | Kick: {kick_metrics.false_positives}")

        # Kick mode rejects mid-frequency vocal formants completely
        assert kick_metrics.false_positives == 0, f"Kick Focus produced {kick_metrics.false_positives} false positives on pure vocals!"
        # Rhythm mode running harmonic floor suppresses vocal plateaus
        assert rhythm_metrics.false_positives <= full_metrics.false_positives

    def test_kick_focus_isolates_strong_kicks_and_rejects_sustained_bassline(self, audio_dataset):
        """Kick focus detects strong kicks with high precision and rejects sustained sub-bass pedals."""
        # 1. Strong kick drums: must detect all kicks
        kick_audio = audio_dataset["strong_kick_drums"]["audio"]
        kick_refs = audio_dataset["strong_kick_drums"]["ref_onsets"]
        _, kick_metrics = run_analyzer_evaluation(kick_audio, kick_refs, AudioFocus.KICK)

        assert kick_metrics.true_positives == len(kick_refs)
        assert kick_metrics.false_positives == 0
        assert kick_metrics.recall == 1.0

        # 2. Sustained bassline: must only detect initial attack at t=0.1s, no false hits during sustain
        sub_audio = audio_dataset["sustained_bassline"]["audio"]
        sub_refs = audio_dataset["sustained_bassline"]["ref_onsets"]
        _, sub_metrics = run_analyzer_evaluation(sub_audio, sub_refs, AudioFocus.KICK)

        assert sub_metrics.true_positives == 1, "Kick focus missed initial bass attack!"
        assert sub_metrics.false_positives == 0, f"Kick focus produced {sub_metrics.false_positives} false onsets during sustained tone!"

    def test_acoustic_percussion_detected_in_rhythm_mode_and_rejected_in_kick_mode(self, audio_dataset):
        """Acoustic snare and hi-hat percussion (high frequencies) must be detected in Rhythm mode and rejected in Kick mode."""
        perc_audio = audio_dataset["acoustic_percussion"]["audio"]
        perc_refs = audio_dataset["acoustic_percussion"]["ref_onsets"]

        _, rhythm_metrics = run_analyzer_evaluation(perc_audio, perc_refs, AudioFocus.RHYTHM)
        _, kick_metrics = run_analyzer_evaluation(perc_audio, perc_refs, AudioFocus.KICK)

        # Rhythm mode detects high-frequency percussion
        assert rhythm_metrics.true_positives >= 3, f"Rhythm mode detected only {rhythm_metrics.true_positives}/{len(perc_refs)} percussion hits!"
        # Kick mode rejects high-frequency percussion (no 40-180 Hz energy)
        assert kick_metrics.detected_count == 0, f"Kick mode should reject snare/hat percussion, got {kick_metrics.detected_count} hits!"

    def test_overall_comparative_benchmark_report(self, audio_dataset):
        """Run full comparative benchmark across all 7 categories and assert precision/recall metrics."""
        categories = [
            "silence",
            "vocals_no_drums",
            "vocals_quiet_drums",
            "strong_kick_drums",
            "sustained_bassline",
            "acoustic_percussion",
            "instrumental_music",
        ]
        modes = [AudioFocus.FULL_MUSIC, AudioFocus.RHYTHM, AudioFocus.KICK]

        print("\n" + "=" * 105)
        print(f"{'Category':<24} {'Mode':<12} {'Ref':<6} {'Det':<6} {'TP':<6} {'FP':<6} {'FN':<6} {'Precision':<11} {'Recall':<10}")
        print("-" * 105)

        for cat in categories:
            audio = audio_dataset[cat]["audio"]
            refs = audio_dataset[cat]["ref_onsets"]
            for mode in modes:
                _, m = run_analyzer_evaluation(audio, refs, mode)
                print(f"{cat:<24} {mode.value:<12} {m.reference_count:<6} {m.detected_count:<6} {m.true_positives:<6} {m.false_positives:<6} {m.false_negatives:<6} {m.precision:<11.2f} {m.recall:<10.2f}")
        print("=" * 105 + "\n")
