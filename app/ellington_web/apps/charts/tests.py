"""Model-layer tests for apps.charts.

Scaffolding tests — assert the model contracts hold:
- slug uniqueness on Songbook / Song
- unique-together constraints on Section / Measure / ChordEvent
- CASCADE semantics down the chain (deleting a Song removes its
  Sections / Measures / ChordEvents)
- nullability invariants (Song can exist without a Songbook;
  Section can have measure_count=None; ChordEvent.voicing_reference
  defaults to {})
- the end-to-end chain reachable in both directions
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.charts.models import (
    ChordEvent,
    ImportSource,
    Measure,
    Section,
    Song,
    Songbook,
)


class SongbookTests(TestCase):
    def test_slug_unique(self):
        Songbook.objects.create(slug="real-book-v1", title="Real Book Vol 1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Songbook.objects.create(slug="real-book-v1", title="duplicate")

    def test_song_count_via_related_manager(self):
        sb = Songbook.objects.create(slug="real-book-v1", title="Real Book Vol 1")
        Song.objects.create(slug="all-the-things-rb1", title="All The Things You Are", songbook=sb)
        Song.objects.create(slug="autumn-leaves-rb1", title="Autumn Leaves", songbook=sb)
        self.assertEqual(sb.songs.count(), 2)


class SongTests(TestCase):
    def test_song_can_exist_without_songbook(self):
        s = Song.objects.create(slug="hand-entered-1", title="My Tune")
        self.assertIsNone(s.songbook)
        self.assertEqual(s.import_source, ImportSource.OTHER)

    def test_song_slug_unique(self):
        Song.objects.create(slug="all-the-things", title="All The Things You Are")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Song.objects.create(slug="all-the-things", title="duplicate")

    def test_songbook_set_null_on_delete(self):
        sb = Songbook.objects.create(slug="rb1", title="Real Book Vol 1")
        s = Song.objects.create(slug="autumn", title="Autumn Leaves", songbook=sb)
        sb.delete()
        s.refresh_from_db()
        self.assertIsNone(s.songbook)


class SectionTests(TestCase):
    def setUp(self):
        self.song = Song.objects.create(slug="autumn-leaves", title="Autumn Leaves")

    def test_section_unique_order_per_song(self):
        Section.objects.create(song=self.song, label="A", order_index=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Section.objects.create(song=self.song, label="A'", order_index=0)

    def test_different_songs_can_share_order_index(self):
        other = Song.objects.create(slug="my-funny-valentine", title="My Funny Valentine")
        Section.objects.create(song=self.song, label="A", order_index=0)
        Section.objects.create(song=other, label="A", order_index=0)  # no conflict

    def test_section_cascades_on_song_delete(self):
        Section.objects.create(song=self.song, label="A", order_index=0)
        Section.objects.create(song=self.song, label="B", order_index=1)
        self.song.delete()
        self.assertEqual(Section.objects.count(), 0)

    def test_measure_count_can_be_null(self):
        s = Section.objects.create(song=self.song, label="A", order_index=0)
        self.assertIsNone(s.measure_count)


class MeasureTests(TestCase):
    def setUp(self):
        song = Song.objects.create(slug="autumn", title="Autumn Leaves")
        self.section = Section.objects.create(song=song, label="A", order_index=0)

    def test_unique_measure_number_per_section(self):
        Measure.objects.create(section=self.section, number_in_section=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Measure.objects.create(section=self.section, number_in_section=1)

    def test_repeat_marker_blank_by_default(self):
        m = Measure.objects.create(section=self.section, number_in_section=1)
        self.assertEqual(m.repeat_marker, "")
        self.assertEqual(m.time_signature_override, "")


class ChordEventTests(TestCase):
    def setUp(self):
        song = Song.objects.create(slug="autumn", title="Autumn Leaves", key="Em", time_signature="4/4")
        section = Section.objects.create(song=song, label="A", order_index=0)
        self.measure = Measure.objects.create(section=section, number_in_section=1)

    def test_unique_chord_event_per_beat(self):
        ChordEvent.objects.create(measure=self.measure, beat=Decimal("1.0"), chord_symbol="Cmaj7")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChordEvent.objects.create(measure=self.measure, beat=Decimal("1.0"), chord_symbol="Am7")

    def test_voicing_reference_defaults_to_empty_dict(self):
        ev = ChordEvent.objects.create(
            measure=self.measure, beat=Decimal("1.0"), chord_symbol="Cmaj7",
        )
        self.assertEqual(ev.voicing_reference, {})

    def test_duration_beats_nullable(self):
        ev = ChordEvent.objects.create(
            measure=self.measure, beat=Decimal("2.5"), chord_symbol="Am7",
        )
        self.assertIsNone(ev.duration_beats)

    def test_chord_event_cascades_on_measure_delete(self):
        ChordEvent.objects.create(measure=self.measure, beat=Decimal("1.0"), chord_symbol="Cmaj7")
        ChordEvent.objects.create(measure=self.measure, beat=Decimal("3.0"), chord_symbol="Am7")
        self.measure.delete()
        self.assertEqual(ChordEvent.objects.count(), 0)


class EndToEndChainTests(TestCase):
    """Songbook → Song → Section → Measure → ChordEvent must be reachable
    in both directions. The reverse traversal is what the iReal Pro
    parser + the comparator's chart-aware mode will use.
    """

    def test_full_chain_creates_and_traverses(self):
        sb = Songbook.objects.create(slug="rb1", title="Real Book Vol 1")
        song = Song.objects.create(
            slug="all-the-things-rb1",
            title="All The Things You Are",
            composer="Jerome Kern",
            key="Ab",
            time_signature="4/4",
            form="AABA",
            songbook=sb,
            import_source=ImportSource.REAL_BOOK_V1,
        )
        section_a = Section.objects.create(song=song, label="A", order_index=0, measure_count=8)
        section_b = Section.objects.create(song=song, label="B", order_index=1, measure_count=8)

        m1 = Measure.objects.create(section=section_a, number_in_section=1)
        Measure.objects.create(section=section_a, number_in_section=2)
        Measure.objects.create(section=section_b, number_in_section=1)

        ChordEvent.objects.create(measure=m1, beat=Decimal("1.0"), chord_symbol="Fm7")
        ChordEvent.objects.create(measure=m1, beat=Decimal("3.0"), chord_symbol="Bb7")

        # Forward traversal: songbook → songs → sections → measures → chord events
        self.assertEqual(sb.songs.count(), 1)
        self.assertEqual(song.sections.count(), 2)
        self.assertEqual(section_a.measures.count(), 2)
        self.assertEqual(section_b.measures.count(), 1)
        self.assertEqual(m1.chord_events.count(), 2)

        # Reverse traversal: chord event → measure → section → song → songbook
        ev = ChordEvent.objects.get(measure=m1, beat=Decimal("1.0"))
        self.assertEqual(ev.measure.section.song.songbook.slug, "rb1")
        self.assertEqual(ev.measure.section.song.import_source, ImportSource.REAL_BOOK_V1)
