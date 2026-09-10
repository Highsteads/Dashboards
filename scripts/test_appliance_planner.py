#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_appliance_scheduler.py
# Description: Contract tests for appliance_planner.py
# Author:      CliveS & Claude Opus 5
# Date:        09-09-2026
# Version:     1.0

import importlib.machinery, importlib.util, os, unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
# Beside the engine in the repo's scripts/ folder; one level up in the estate's
# Python Scripts/tests/. Try both rather than assuming a layout.
SRC = os.environ.get("SCHED", os.path.join(HERE, "appliance_planner.py"))
if not os.path.exists(SRC):
    SRC = os.path.join(os.path.dirname(HERE), "appliance_planner.py")
spec = importlib.util.spec_from_loader("asch", importlib.machinery.SourceFileLoader("asch", SRC))
asch = importlib.util.module_from_spec(spec); spec.loader.exec_module(asch)

LON = ZoneInfo("Europe/London")
UTC = ZoneInfo("UTC")


def local(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=LON)


def wash(minutes=60, kwh=1.2):
    return asch.Appliance("w", "the washing machine", minutes, kwh, 1936,
                          measured_from="history", cycles_measured=41)


def solar(**by_local_hour):
    """Build a UTC-keyed forecast from local hours, the way the real file is keyed."""
    out = {}
    for hour, kwh in by_local_hour.items():
        dt = local(2026, 6, 15, int(hour))
        out[dt.astimezone(UTC).strftime("%Y-%m-%dT%H:00:00Z")] = {"kwh": kwh}
    return out


FLAT_HOUSE = {"weekday": {str(h): 0.5 for h in range(24)},
              "weekend": {str(h): 0.9 for h in range(24)}}


def tracker(pence=25.0, day=15):
    return [{"start": local(2026, 6, day, 0), "end": local(2026, 6, day + 1, 0), "pence": pence}]


def battery(soc=50.0, cap=35.04, reserve=15.0, eff=0.94):
    return asch.Battery(soc, cap, reserve, eff)


# ---------------------------------------------------------------------------

class TestHourShares(unittest.TestCase):
    def test_a_run_inside_one_hour(self):
        s = asch.hour_shares(local(2026, 6, 15, 10, 0), 30)
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0][1], 1.0)

    def test_a_run_spanning_two_hours_splits_by_the_minute(self):
        s = asch.hour_shares(local(2026, 6, 15, 10, 30), 60)
        self.assertEqual(len(s), 2)
        self.assertAlmostEqual(s[0][1], 0.5)
        self.assertAlmostEqual(s[1][1], 0.5)

    def test_shares_always_sum_to_one(self):
        for start_min in (0, 7, 15, 29, 45, 59):
            for length in (20, 61, 90, 159):
                s = asch.hour_shares(local(2026, 6, 15, 9, start_min), length)
                self.assertAlmostEqual(sum(f for _, f in s), 1.0, places=9)

    def test_a_run_across_midnight_does_not_wrap_to_hour_zero(self):
        s = asch.hour_shares(local(2026, 6, 15, 23, 30), 60)
        self.assertEqual([h.hour for h, _ in s], [23, 0])
        self.assertEqual(s[1][0].day, 16, "the second hour is the NEXT day")

    def test_a_zero_length_run_is_refused(self):
        with self.assertRaises(ValueError):
            asch.hour_shares(local(2026, 6, 15, 10), 0)


class TestAbsentIsNeverZero(unittest.TestCase):
    """A forecast that has not arrived is not a forecast of darkness."""

    def test_a_missing_forecast_hour_is_unknown_not_zero(self):
        self.assertIsNone(asch.solar_for_hour({}, local(2026, 6, 15, 10)))

    def test_a_real_zero_is_a_zero(self):
        self.assertEqual(asch.solar_for_hour(solar(**{"10": 0.0}), local(2026, 6, 15, 10)), 0.0)

    def test_a_missing_house_hour_is_unknown(self):
        self.assertIsNone(asch.house_for_hour({"weekday": {}}, local(2026, 6, 15, 10)))

    def test_surplus_is_unknown_if_either_side_is(self):
        self.assertIsNone(asch.surplus_for_hour({}, FLAT_HOUSE, local(2026, 6, 15, 10)))
        self.assertIsNone(asch.surplus_for_hour(solar(**{"10": 3.0}), {"weekday": {}},
                                                local(2026, 6, 15, 10)))

    def test_an_unknown_hour_refuses_to_cost_rather_than_guessing(self):
        with self.assertRaises(asch.NoPlan):
            asch.cost_candidate(wash(), local(2026, 6, 15, 10), battery(), {},
                                FLAT_HOUSE, tracker(), local(2026, 6, 15, 9))

    def test_a_missing_price_refuses_to_cost(self):
        with self.assertRaises(asch.NoPlan):
            asch.cost_candidate(wash(), local(2026, 6, 15, 10), battery(soc=15.0),
                                solar(**{"10": 0.0, "11": 0.0}), FLAT_HOUSE, [],
                                local(2026, 6, 15, 9))


class TestWeekdayVersusWeekend(unittest.TestCase):
    def test_a_monday_uses_the_weekday_profile(self):
        self.assertEqual(asch.house_for_hour(FLAT_HOUSE, local(2026, 6, 15, 10)), 0.5)

    def test_a_saturday_uses_the_weekend_profile(self):
        self.assertEqual(asch.house_for_hour(FLAT_HOUSE, local(2026, 6, 20, 10)), 0.9)


class TestRatesTakeBothShapes(unittest.TestCase):
    def test_a_tracker_span_covers_the_whole_day(self):
        r = tracker(24.0)
        for h in (0, 9, 17, 23):
            self.assertEqual(asch.rate_for(r, local(2026, 6, 15, h)), 24.0)

    def test_agile_half_hours_are_read_individually(self):
        r = [{"start": local(2026, 6, 15, 10, 0), "end": local(2026, 6, 15, 10, 30), "pence": 5.0},
             {"start": local(2026, 6, 15, 10, 30), "end": local(2026, 6, 15, 11, 0), "pence": 31.0}]
        self.assertEqual(asch.rate_for(r, local(2026, 6, 15, 10, 15)), 5.0)
        self.assertEqual(asch.rate_for(r, local(2026, 6, 15, 10, 45)), 31.0)

    def test_a_day_published_with_a_gap_reports_the_gap_rather_than_a_neighbour(self):
        """Octopus routinely publish 46 of a day's 48 half hours."""
        r = [{"start": local(2026, 6, 15, 10, 0), "end": local(2026, 6, 15, 10, 30), "pence": 5.0}]
        self.assertIsNone(asch.rate_for(r, local(2026, 6, 15, 11, 0)))

    def test_the_end_of_a_span_belongs_to_the_next_one(self):
        r = [{"start": local(2026, 6, 15, 10, 0), "end": local(2026, 6, 15, 10, 30), "pence": 5.0}]
        self.assertIsNone(asch.rate_for(r, local(2026, 6, 15, 10, 30)))


class TestTheBatteryIsAStockNotARow(unittest.TestCase):
    """The trap this engine exists to avoid: promising the same kWh to every hour."""

    def test_surplus_charges_it(self):
        got = asch.carry_battery_forward(battery(soc=50.0), solar(**{"10": 3.0, "11": 3.0}),
                                         FLAT_HOUSE, local(2026, 6, 15, 10), local(2026, 6, 15, 12))
        self.assertGreater(got, battery(soc=50.0).usable_kwh)

    def test_a_deficit_drains_it(self):
        got = asch.carry_battery_forward(battery(soc=50.0), solar(**{"10": 0.0, "11": 0.0}),
                                         FLAT_HOUSE, local(2026, 6, 15, 10), local(2026, 6, 15, 12))
        self.assertLess(got, battery(soc=50.0).usable_kwh)

    def test_it_never_charges_past_the_pack(self):
        got = asch.carry_battery_forward(battery(soc=99.0), solar(**{str(h): 9.0 for h in range(24)}),
                                         FLAT_HOUSE, local(2026, 6, 15, 0), local(2026, 6, 15, 23))
        b = battery(soc=99.0)
        self.assertLessEqual(got, b.capacity_kwh - b.reserve_kwh + 1e-6)

    def test_it_never_drains_below_the_reserve(self):
        got = asch.carry_battery_forward(battery(soc=20.0), solar(**{str(h): 0.0 for h in range(24)}),
                                         FLAT_HOUSE, local(2026, 6, 15, 0), local(2026, 6, 15, 23))
        self.assertGreaterEqual(got, 0.0)

    def test_a_later_start_does_not_see_energy_an_earlier_hour_already_spent(self):
        dark = solar(**{str(h): 0.0 for h in range(24)})
        early = asch.carry_battery_forward(battery(soc=30.0), dark, FLAT_HOUSE,
                                           local(2026, 6, 15, 0), local(2026, 6, 15, 2))
        late = asch.carry_battery_forward(battery(soc=30.0), dark, FLAT_HOUSE,
                                          local(2026, 6, 15, 0), local(2026, 6, 15, 20))
        self.assertLess(late, early, "the house has been eating it all day")

    def test_costing_a_later_start_sees_a_battery_the_house_has_been_eating(self):
        """The mutation that replaced carry_battery_forward() with today's SOC survived the
        first sweep: carry_battery_forward was tested, but nothing proved cost_candidate
        called it. Test the behaviour, not the helper."""
        dark = solar(**{str(h): 0.0 for h in range(24)})
        a = wash(60, 1.0)
        early = asch.cost_candidate(a, local(2026, 6, 15, 1), battery(soc=24.0), dark,
                                    FLAT_HOUSE, tracker(25.0), local(2026, 6, 15, 0))
        late = asch.cost_candidate(a, local(2026, 6, 15, 20), battery(soc=24.0), dark,
                                   FLAT_HOUSE, tracker(25.0), local(2026, 6, 15, 0))
        self.assertEqual(early.grid_kwh, 0.0, "at 1am the battery still has 3.2 kWh spare")
        self.assertGreater(late.grid_kwh, 0.0,
                           "by 8pm the house has drained it, so the wash must buy from the grid")

    def test_the_reserve_is_a_floor_the_appliance_cannot_dig_below(self):
        """Asserting >= 0.0 proved nothing - max(0, stored - floor) gives that for free."""
        dark = solar(**{"10": 0.0, "11": 0.0})
        just_above = asch.Battery(16.0, 35.04, 15.0, 0.94)     # 0.35 kWh above the reserve
        s = asch.cost_candidate(wash(60, 1.0), local(2026, 6, 15, 10), just_above, dark,
                                FLAT_HOUSE, tracker(25.0), local(2026, 6, 15, 10))
        self.assertLessEqual(s.battery_kwh, just_above.usable_kwh + 1e-6,
                             "it may not take one watt-hour below the resilience reserve")
        self.assertGreater(s.grid_kwh, 0.0, "the rest has to be bought")

    def test_the_reserve_is_not_actually_eaten_during_a_long_dark_stretch(self):
        """Removing the floor survived the first sweep because usable_kwh clamps at zero
        either way - a pack held AT the reserve and one driven to minus four both read as
        'nothing spare'. The difference only shows when the sun comes back: a real pack
        recovers from the reserve, a modelled hole has to climb out of it first."""
        by = {str(h): 0.0 for h in range(24)}
        by.update({str(h): 4.0 for h in (12, 13, 14)})     # dark morning, then sun
        recovered = asch.carry_battery_forward(
            asch.Battery(16.0, 35.04, 15.0, 1.0), solar(**by), FLAT_HOUSE,
            local(2026, 6, 15, 0), local(2026, 6, 15, 15))
        # 3 hours x (4.0 - 0.5) = 10.5 kWh of charging after the reserve was reached.
        self.assertGreater(recovered, 9.0,
                           "the morning must not have dug a hole for the sun to fill")

    def test_charging_is_lossy(self):
        lossless = asch.Battery(50.0, 35.04, 15.0, 1.0)
        lossy    = asch.Battery(50.0, 35.04, 15.0, 0.80)
        sunny = solar(**{"10": 4.0, "11": 4.0})
        a = asch.carry_battery_forward(lossless, sunny, FLAT_HOUSE,
                                       local(2026, 6, 15, 10), local(2026, 6, 15, 12))
        b = asch.carry_battery_forward(lossy, sunny, FLAT_HOUSE,
                                       local(2026, 6, 15, 10), local(2026, 6, 15, 12))
        self.assertGreater(a, b, "a lossy pack must bank less of the same sunshine")

    def test_the_starting_hours_surplus_is_not_banked_AND_claimed(self):
        """It was, until 09-Sep-2026: the carry-forward walked through the hour the run
        begins in, charging the battery with surplus that cost_candidate then spent again
        as direct sun. A run wholly inside one sunny hour must not come out cheaper than
        that hour's surplus allows."""
        by = {str(h): 0.0 for h in range(24)}
        by.update({"14": 1.3})                       # surplus 0.8 kWh in hour 14
        s = asch.cost_candidate(wash(60, 1.0), local(2026, 6, 15, 14),
                                asch.Battery(15.0, 35.04, 15.0, 0.94), solar(**by),
                                FLAT_HOUSE, tracker(99.0), local(2026, 6, 15, 9))
        self.assertAlmostEqual(s.solar_kwh, 0.8, places=2)
        self.assertAlmostEqual(s.grid_kwh, 0.2, places=2,
                               msg="0.8 of surplus cannot cover 1.0 of demand")

    def test_a_run_present_for_half_an_hour_claims_half_that_hours_surplus(self):
        """The fixture has to make the constraint BITE: with surplus 2.0 and demand 1.0 the
        demand is binding either way, so scaling by occupancy or not gives the same answer
        and the test asserts nothing. Surplus 1.6 halved is 0.8, which does not cover 1.0."""
        by = {str(h): 0.0 for h in range(24)}
        by.update({"14": 2.1})                       # surplus 1.6 kWh across the whole hour
        s = asch.cost_candidate(wash(30, 1.0), local(2026, 6, 15, 14, 30),
                                asch.Battery(15.0, 35.04, 15.0, 0.94), solar(**by),
                                FLAT_HOUSE, tracker(99.0), local(2026, 6, 15, 9))
        self.assertAlmostEqual(s.solar_kwh, 0.8, places=2,
                               msg="half an hour of a 1.6 kWh surplus is 0.8, not 1.6")
        self.assertAlmostEqual(s.grid_kwh, 0.2, places=2)

    def test_a_run_filling_a_whole_hour_claims_all_of_it(self):
        by = {str(h): 0.0 for h in range(24)}
        by.update({"14": 1.3})                       # surplus 0.8 kWh
        s = asch.cost_candidate(wash(60, 1.0), local(2026, 6, 15, 14),
                                asch.Battery(15.0, 35.04, 15.0, 0.94), solar(**by),
                                FLAT_HOUSE, tracker(99.0), local(2026, 6, 15, 9))
        self.assertAlmostEqual(s.solar_kwh, 0.8, places=2,
                               msg="a full hour claims the full hour, not 60/61ths of it")

    def test_an_unknown_hour_leaves_the_stock_alone(self):
        got = asch.carry_battery_forward(battery(soc=50.0), {}, FLAT_HOUSE,
                                         local(2026, 6, 15, 0), local(2026, 6, 15, 12))
        self.assertAlmostEqual(got, battery(soc=50.0).usable_kwh)


class TestTheOrderEnergyIsDrawnFrom(unittest.TestCase):
    def test_surplus_is_used_before_anything_else(self):
        s = asch.cost_candidate(wash(60, 1.0), local(2026, 6, 15, 10), battery(soc=50.0),
                                solar(**{"10": 5.0, "11": 5.0}), FLAT_HOUSE, tracker(),
                                local(2026, 6, 15, 10))
        self.assertAlmostEqual(s.solar_kwh, 1.0, places=3)
        self.assertEqual(s.grid_kwh, 0.0)
        self.assertEqual(s.cost_p, 0.0)

    def test_the_battery_covers_what_the_sun_cannot(self):
        s = asch.cost_candidate(wash(60, 1.0), local(2026, 6, 15, 10), battery(soc=50.0),
                                solar(**{"10": 0.0, "11": 0.0}), FLAT_HOUSE, tracker(),
                                local(2026, 6, 15, 10))
        self.assertAlmostEqual(s.battery_kwh, 1.0, places=3)
        self.assertEqual(s.grid_kwh, 0.0)

    def test_the_grid_covers_what_neither_can(self):
        s = asch.cost_candidate(wash(60, 1.0), local(2026, 6, 15, 10), battery(soc=15.0),
                                solar(**{"10": 0.0, "11": 0.0}), FLAT_HOUSE, tracker(25.0),
                                local(2026, 6, 15, 10))
        self.assertAlmostEqual(s.grid_kwh, 1.0, places=3)
        self.assertAlmostEqual(s.cost_p, 25.0, places=1)


class TestChoosing(unittest.TestCase):
    def sunny_afternoon(self):
        by = {str(h): 0.0 for h in range(24)}
        by.update({"13": 6.0, "14": 6.0})
        return solar(**by)

    def test_it_picks_the_sunny_window(self):
        best, _ = asch.plan(wash(60, 1.0), local(2026, 6, 15, 9), local(2026, 6, 15, 18),
                            battery(soc=15.0), self.sunny_afternoon(), FLAT_HOUSE, tracker())
        self.assertIn(best.start.hour, (13, 14))
        self.assertEqual(best.grid_kwh, 0.0)

    def test_grid_import_outranks_pennies(self):
        """Needs a case where the two orderings DISAGREE. The first version of this test put
        the sun in the expensive hours, which made the same window win on either ranking - it
        passed with the sort key reversed, so it was asserting nothing."""
        by = {str(h): 0.0 for h in range(24)}
        by.update({"14": 1.3})                      # surplus 0.8 kWh: covers most, not all
        # Dirt cheap in the morning, ruinous in the afternoon.
        rates = [{"start": local(2026, 6, 15, 0), "end": local(2026, 6, 15, 13), "pence": 1.0},
                 {"start": local(2026, 6, 15, 13), "end": local(2026, 6, 16, 0), "pence": 99.0}]
        best, every = asch.plan(wash(60, 1.0), local(2026, 6, 15, 9), local(2026, 6, 15, 18),
                                battery(soc=15.0), solar(**by), FLAT_HOUSE, rates)
        cheapest = min(every, key=lambda s: s.cost_p)
        least_import = min(every, key=lambda s: s.grid_kwh)
        self.assertGreater(cheapest.grid_kwh, least_import.grid_kwh,
                           "the fixture must make the two orderings actually disagree")
        self.assertAlmostEqual(best.grid_kwh, least_import.grid_kwh, places=3)
        self.assertEqual(best.start.hour, 14,
                         "importing least beats importing cheaply - that is the stated KPI")

    def test_an_impossible_deadline_says_so_and_says_when_it_would_finish(self):
        with self.assertRaises(asch.NoPlan) as cm:
            asch.plan(wash(61, 1.0), local(2026, 6, 15, 17, 30), local(2026, 6, 15, 18),
                      battery(), self.sunny_afternoon(), FLAT_HOUSE, tracker())
        self.assertIn("finished by", str(cm.exception))

    def test_a_deadline_in_the_past_says_THAT_rather_than_blaming_the_cycle_length(self):
        """Without its own check this still raises, from candidate_starts, but with a
        message about the cycle not fitting - which sends the reader to the wrong problem.
        The guard earns its place on the wording, so the wording is what to assert."""
        with self.assertRaises(asch.NoPlan) as cm:
            asch.plan(wash(), local(2026, 6, 15, 12), local(2026, 6, 15, 9),
                      battery(), self.sunny_afternoon(), FLAT_HOUSE, tracker())
        self.assertIn("already passed", str(cm.exception))

    def test_candidates_land_on_the_half_hour(self):
        got = asch.candidate_starts(local(2026, 6, 15, 9, 7), local(2026, 6, 15, 18), wash())
        self.assertEqual([c.minute for c in got][:4], [30, 0, 30, 0])

    def test_no_candidate_would_overrun_the_deadline(self):
        a = wash(61, 1.0)
        deadline = local(2026, 6, 15, 18)
        for c in asch.candidate_starts(local(2026, 6, 15, 9), deadline, a):
            self.assertLessEqual(c + timedelta(minutes=a.duration_minutes), deadline)


class TestItSpeaksEnglish(unittest.TestCase):
    def message(self, **kw):
        now, deadline = local(2026, 6, 15, 9), local(2026, 6, 15, 18)
        by = {str(h): 0.0 for h in range(24)}; by.update({"13": 6.0, "14": 6.0})
        best, every = asch.plan(wash(60, kw.get("kwh", 1.0)), now, deadline,
                                battery(soc=kw.get("soc", 15.0)), solar(**by), FLAT_HOUSE,
                                tracker(kw.get("p", 25.0)))
        return asch.describe(wash(60, kw.get("kwh", 1.0)), best, every, now, deadline)

    def test_it_is_pure_ascii(self):
        self.message().encode("ascii")

    def test_it_is_sentences_not_a_value_dump(self):
        m = self.message()
        self.assertNotIn("|", m)
        self.assertNotIn(" = ", m)
        self.assertNotIn(";", m)          # the standing no-semicolons rule
        self.assertTrue(m.rstrip().endswith("."))

    def test_it_names_a_time_the_way_a_person_does(self):
        self.assertRegex(self.message(), r"\d{1,2}(:\d{2})?(am|pm)")
        self.assertNotRegex(self.message(), r"\b\d{2}:\d{2}\b(?!am|pm)")

    def test_it_fits_one_pushover(self):
        self.assertLess(len(self.message()), 1024)

    def test_it_says_where_the_figures_came_from(self):
        self.assertIn("real cycles", self.message())

    def test_the_clock_says_4pm_not_16_00(self):
        self.assertEqual(asch._clock(local(2026, 6, 15, 16, 0)), "4pm")
        self.assertEqual(asch._clock(local(2026, 6, 15, 1, 45)), "1:45am")
        self.assertEqual(asch._clock(local(2026, 6, 15, 12, 0)), "12pm")
        self.assertEqual(asch._clock(local(2026, 6, 15, 0, 0)), "12am")

    def test_a_tiny_grid_draw_is_never_printed_as_zero(self):
        """0.04 kWh at one decimal place is "0.0", which beside a real cost reads as a bug."""
        best = asch.Slot(local(2026, 6, 15, 10), local(2026, 6, 15, 11), 0.04, 0.9, 0.70, 0.0)
        other = asch.Slot(local(2026, 6, 15, 17), local(2026, 6, 15, 18), 0.74, 28.1, 0.0, 0.0)
        m = asch.describe(wash(61, 0.74), best, [best, other],
                          local(2026, 6, 15, 9), local(2026, 6, 15, 20))
        self.assertNotIn("0.0 of its", m)
        self.assertIn("Nearly all", m)

    def test_a_real_grid_draw_is_still_quantified(self):
        best = asch.Slot(local(2026, 6, 15, 10), local(2026, 6, 15, 11), 0.5, 12.0, 0.24, 0.0)
        m = asch.describe(wash(61, 0.74), best, [best],
                          local(2026, 6, 15, 9), local(2026, 6, 15, 20))
        self.assertIn("0.5 of its 0.7 kWh", m)

    def test_a_deadline_tomorrow_is_not_called_today(self):
        """The first live run said 'before 4pm today' of a deadline that was the next day."""
        self.assertEqual(asch._day_word(local(2026, 6, 16, 16), local(2026, 6, 15, 21)),
                         "tomorrow")

    def test_a_deadline_later_the_same_day_is_today(self):
        self.assertEqual(asch._day_word(local(2026, 6, 15, 16), local(2026, 6, 15, 9)),
                         "today")

    def test_a_deadline_further_out_is_named_by_its_weekday(self):
        self.assertEqual(asch._day_word(local(2026, 6, 18, 16), local(2026, 6, 15, 9)),
                         "Thursday")

    def test_the_message_says_tomorrow_when_the_deadline_is_tomorrow(self):
        now, deadline = local(2026, 6, 15, 21), local(2026, 6, 16, 16)
        by = {str(h): 0.0 for h in range(24)}
        best, every = asch.plan(wash(60, 1.0), now, deadline, battery(soc=80.0),
                                solar(**{**by, **{str(h): 0.0 for h in range(24)}}),
                                FLAT_HOUSE, [{"start": local(2026, 6, 15, 0),
                                              "end": local(2026, 6, 17, 0), "pence": 25.0}])
        m = asch.describe(wash(60, 1.0), best, every, now, deadline)
        self.assertIn("tomorrow", m)
        self.assertNotIn("today", m)

    def test_pence_become_pounds_when_they_should(self):
        self.assertEqual(asch._pence(37.4), "37p")
        self.assertEqual(asch._pence(250.0), "2.50 pounds")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---------------------------------------------------------------------------
# v2.0: every metered appliance, each measured from its own history
# ---------------------------------------------------------------------------

class TestNamingFromTheMonitorDevice(unittest.TestCase):
    """The key names the deadline variable, so it has to be stable AND has to keep the one
    the washing machine already uses."""

    def test_the_washing_machine_keeps_its_existing_key(self):
        self.assertEqual(asch.appliance_key("Washing Machine Appliance Monitoring"),
                         "washing_machine")

    def test_a_dryer_added_later_needs_no_wiring_up(self):
        self.assertEqual(asch.appliance_key("Tumble Dryer Appliance Monitor"), "tumble_dryer")
        self.assertEqual(asch.appliance_key("Dishwasher"), "dishwasher")

    def test_punctuation_becomes_single_underscores(self):
        self.assertEqual(asch.appliance_key("Utility Room Tumble-Dryer Monitoring"),
                         "utility_room_tumble_dryer")

    def test_a_nameless_device_does_not_produce_a_broken_key(self):
        self.assertEqual(asch.appliance_key("   "), "")
        self.assertEqual(asch.appliance_label("   "), "the appliance")

    def test_the_label_reads_as_a_sentence(self):
        self.assertEqual(asch.appliance_label("Tumble Dryer Appliance Monitoring"),
                         "the tumble dryer")


class TestWhatCountsAsACycle(unittest.TestCase):
    def test_lifetime_meter_totals_are_discarded(self):
        # These columns have had the Shelly's lifetime kWh written into them - a 3446 kWh
        # wash - and averaging that in would wreck the median.
        self.assertEqual(asch.plausible_cycles([0.74, 3446.59, 0.71], "kwh"), [0.74, 0.71])

    def test_a_repeated_report_is_one_cycle(self):
        self.assertEqual(asch.plausible_cycles([61, 61, 61, 58], "minutes"), [61, 58])

    def test_a_value_returning_later_counts_again(self):
        self.assertEqual(asch.plausible_cycles([61, 58, 61], "minutes"), [61, 58, 61])

    def test_nonsense_types_are_dropped(self):
        self.assertEqual(asch.plausible_cycles([61, None, "x", 58], "minutes"), [61, 58])

    def test_the_bounds_exclude_nonsense_not_unusual_cycles(self):
        # This machine's real spread is 56-159 minutes and 0.58-1.03 kWh.
        self.assertEqual(asch.plausible_cycles([56, 159], "minutes"), [56, 159])
        self.assertEqual(asch.plausible_cycles([0.58, 1.03], "kwh"), [0.58, 1.03])


class TestAProfileIsMeasuredOrItIsAbsent(unittest.TestCase):
    def test_enough_cycles_gives_a_profile(self):
        # Values must VARY: consecutive repeats are collapsed, so six identical readings are
        # one cycle as far as this is concerned. Real history varies; a fixture that does not
        # is testing the collapse rather than the profile.
        a = asch.profile_from_cycles("w", "the washing machine",
                                     [61, 60, 62, 58, 61, 66],
                                     [0.74, 0.71, 0.77, 0.69, 0.74, 0.80],
                                     [1936, 1920, 1950, 1900, 1936, 1990])
        self.assertIsNotNone(a)
        self.assertEqual(a.duration_minutes, 61)
        self.assertAlmostEqual(a.energy_kwh, 0.74, places=2)
        self.assertEqual(a.cycles_measured, 6)

    def test_too_few_cycles_gives_NOTHING_rather_than_a_median_of_two(self):
        """The page's whole claim is that its timings come from the machine. A median of two
        is not that, and a figure off the manual certainly is not."""
        self.assertIsNone(asch.profile_from_cycles("w", "l", [61, 60], [0.7, 0.7], [1900, 1900]))

    def test_a_machine_that_has_never_run_gives_nothing(self):
        self.assertIsNone(asch.profile_from_cycles("w", "l", [], [], []))

    def test_contaminated_history_is_cleaned_before_counting(self):
        # Six raw values, but only four are cycles - so it must refuse, not quote four.
        self.assertIsNone(asch.profile_from_cycles(
            "w", "l", [61, 9972, 60, 9972, 58, 62], [0.7, 3446, 0.7, 3446, 0.7, 0.7],
            [1900] * 6))

    def test_a_missing_peak_column_does_not_stop_a_profile(self):
        a = asch.profile_from_cycles("w", "l", [61, 60, 62, 58, 61, 66],
                                     [0.74, 0.71, 0.77, 0.69, 0.74, 0.80], [])
        self.assertIsNotNone(a)
        self.assertEqual(a.peak_watts, 0.0)

    def test_the_profile_says_how_many_cycles_it_rests_on(self):
        mins = [61, 60, 62, 58, 61, 66, 59]
        kwh = [0.74, 0.71, 0.77, 0.69, 0.74, 0.80, 0.72]
        a = asch.profile_from_cycles("w", "l", mins, kwh, [1936] * 7)
        self.assertIn("7 cycles", a.measured_from)

    def test_two_identical_runs_back_to_back_are_counted_once(self):
        """A known and accepted limitation, written down rather than discovered later. The
        history re-reports the same value on row after row between cycles, so collapsing runs
        is what makes the count mean anything at all — the cost is that two genuinely
        identical consecutive cycles merge. It does not bias the median, only the count, and
        the real spread here (56-159 min, 0.58-1.03 kWh) makes an exact repeat uncommon."""
        self.assertEqual(asch.plausible_cycles([61, 61], "minutes"), [61])
        self.assertEqual(asch.plausible_cycles([61, 60, 61], "minutes"), [61, 60, 61])


class TestMedian(unittest.TestCase):
    def test_odd(self):   self.assertEqual(asch.median([3, 1, 2]), 2)
    def test_even(self):  self.assertEqual(asch.median([1, 2, 3, 4]), 2.5)
    def test_empty(self): self.assertIsNone(asch.median([]))
