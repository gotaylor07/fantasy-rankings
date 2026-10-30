# Fantasy rankings: football (full PPR) and basketball (points)

Two pages with the same features, linked by the **Football / Basketball** switch at the top: `site/index.html` for football and `site/basketball.html` for basketball. `update.py` builds both (`--sport football` or `--sport basketball` builds one).

Pulls rankings from several sites, averages each player's position rank, and builds a single HTML page with two tabs:

- **Player rankings**: **Upcoming week**, **Rest of season**, and **Dynasty**, each split by QB / RB / WR / TE, plus K and D/ST on the week and rest-of-season boards. Click any player for their profile (photo, bio, age, height, weight, this season's position finish, next opponent, and the share of ESPN leagues that roster them) and game logs: this season plus a tab for every past season back to 2009, with PPR points, snap share, targets, carries and the rest of the box score, week by week.
- **My league**: connect a Sleeper or ESPN league. **Overview** has power rankings, every team's league rank at each position, and projected finishing records with playoff odds. **Lineup** suggests your best lineup for the upcoming week. **Trades** shows your position needs, suggested trades, and a trade analyzer. **Waivers** suggests pickups (with who to drop) and lists the best available players at each position.

## Run it

Needs Python 3.9+.

```
pip install -r requirements.txt
python3 update.py --demo     # fake players: site/demo.html and site/demo-basketball.html
python3 update.py            # live data: site/index.html and site/basketball.html
```

Open `site/index.html` in your browser, no server needed. Past seasons' game logs are in `site/index.history.js` next to it (keep the two together); the page loads that file the first time you open a player.

The first live run downloads every past season since 2009 (about 300 requests, a few minutes). Finished seasons never change, so they're cached in `data/cache/history/` and later runs skip them.

Options: `--week 9` overrides the detected upcoming week, `--season 2026` overrides the season.

## Sources

| Ranking | Sources |
| --- | --- |
| Upcoming week | Sleeper (projected PPR points), FantasyPros (expert consensus). K and D/ST from both |
| Rest of season | Sleeper (projected points summed through Week 18), FantasyPros ROS, FantasyCalc (redraft values). K and D/ST from Sleeper and FantasyPros |
| Dynasty | FantasyCalc, KeepTradeCut, FantasyPros dynasty |

How the average works: each source is converted to a rank within each position, then a player's ranks are averaged across the sources that list them. A player needs to appear in at least two sources. If a source fails during a run, the others still publish and the page notes which one was missing. If every source fails for a ranking, the previous good board stays up.

## Basketball

Everything on the football page works the same way on the basketball page; these are the differences.

- **Scoring is fantasy points.** The rankings use ESPN's standard points scoring (PTS 1, 3PM 1, FGM 2, FGA −1, FTM 1, FTA −1, REB 1, AST 2, STL 4, BLK 4, TO −2). On **My league**, every projection and box score is re-scored with that league's own settings, read from Sleeper or ESPN.
- **Rankings** have an Overall board plus PG / SG / SF / PF / C. Players are listed at every position they're eligible for.

  | Board | Sources |
  | --- | --- |
  | This week | Sleeper (projected points for each remaining game this week, so more games rank higher), Recent form (points per game over the last 14 days × games left this week) |
  | Rest of season | Sleeper (every remaining game's projection), Season pace (points per game so far × games left), FantasyPros ROS |
  | Dynasty | FantasyPros dynasty, Sleeper dynasty draft position |

  FantasyPros' NBA rankings are built for category leagues, so they're one voice among the points-based sources.
- **Lineups are daily.** A week's score is the best lineup each day among players whose team plays that day. The league's **This week** tab shows the rest of the week day by day: who to start, and who to sit on days with more players than spots.
- **Roster value** (trades, waivers, position strengths) is points per week over the next four weeks of games, so a player whose team plays more is worth more. **G/F/UTIL** is the flex row in position strengths.
- **Injuries** use ESPN's NBA report. Chance to play is estimated from the status (Day-To-Day 55%, Questionable 50%, Doubtful 15%, Probable 90%) and adjusted by phrases in the latest note ("expected to play", "ruled out", "game-time decision"). Tune it in `chance_to_play` in `rankings/nba/build.py`.
- **Past seasons** go back to 2017-18, one file per season (`site/basketball.2025.js` and so on) that loads when you click its tab. The first run downloads them all (a couple of minutes); they're cached in `data/cache/nba_history/`.
- **Seasons** are named by the year they start (2026 = 2026-27), as Sleeper does; ESPN uses the ending year, which `update.py` handles.
- **Leagues:** Sleeper and public ESPN basketball leagues connect from the page, as football does. `--espn-login` finds your ESPN basketball leagues too; in `leagues.json`, a basketball league has `"sport": "basketball"`.
- **Things to know:** Sleeper has no ESPN ids for NBA players, so ESPN rosters are matched by name. ESPN scores basketball by day, and the build maps those days to dates; if that lookup fails, ESPN basketball leagues can't line up their weeks and say so.

## Update every Tuesday

Run `update.py` on a schedule. For football, Tuesday evening is a good time: Monday night's game is done, and most sites have refreshed their weekly numbers by then. During the NBA season, run it every morning instead, since basketball lineups, injuries and projections change daily (football just gets refreshed more often, which is harmless).

macOS or Linux (cron), every Tuesday at 6:00 pm:

```
crontab -e
0 18 * * 2 cd /full/path/to/fantasy-rankings && /usr/bin/python3 update.py >> data/update.log 2>&1
# or, during basketball season, every morning at 8:00:
0 8 * * * cd /full/path/to/fantasy-rankings && /usr/bin/python3 update.py >> data/update.log 2>&1
```

Windows: Task Scheduler, weekly on Tuesday, action `python`, arguments `update.py`, start in the project folder. The computer has to be on (or wake) at that time.

## Weekly slate

The **Weekly slate** tab lists every game this week (football: the NFL week; basketball: Monday to Sunday, with a tab per day) with team records, TV, and the pre-game spread, over/under and moneylines. Lines are saved by `update.py` because ESPN removes them from its scoreboard once a game starts, so they reflect the last daily build.

Scores update live from ESPN's public scoreboard: every 20 seconds while any game is in progress, every 5 minutes otherwise, and only while the page is open and visible. Live football games also show down and distance, possession, the last play and ESPN's live win chance. The banner on top cycles through big plays (football: touchdowns, turnovers and gains of 20+ yards, from each game's play-by-play) or player highs (basketball: each team's top performer).

**Weeks:** the slate opens on the current week; the ‹ › arrows step to past weeks (final scores) and upcoming ones. A football week runs Tuesday to Monday, so the site moves to the next week on Tuesday morning, after Monday night's game. Dates are worked out in US Eastern time, since GitHub's servers run on UTC.

**Team schedules:** click a team's name on a game card or in a game window for its whole season: results with W/L and scores for games played, date, time and TV for the rest, with any game opening its plays and box score.

**Game view:** click any game (or a highlight in the banner) to follow it. **Live plays** is a play-by-play feed, newest on top: new plays slide in above the old ones and nothing is removed, so you can scroll back through the whole game. If you've scrolled down, your place is kept and a "new plays" button takes you back up. Football groups plays into drives with a card for each drive's result, and scoring plays, turnovers and gains of 20+ yards stand out. **Box score** has each team's player stats (football: passing, rushing, receiving and more; basketball: starters and bench), with players on this site linked to their profiles. A live game refreshes every 10 seconds while its window is open.

**Live fantasy matchups:** once the week's games start, **My league** refreshes your league's scores every minute (Sleeper and public ESPN leagues; private ESPN leagues and the demo league can't be refreshed from the page). The Matchup tab then shows the lineups each manager actually set, each starter's live points and game status, and win chances recomputed from the points already scored plus each starter's projection scaled by how much of his game is left.

ESPN's servers turn away automated browsers (headless Chrome), so automated tests of the live features need a normal browser user agent; real visitors aren't affected.

## Connecting a league

On the **My league** tab:

- **Sleeper**: enter your username. Sleeper's API is public, so no password is needed. All of your leagues for the season appear in the league picker.
- **ESPN, public league**: paste your league ID, or the league URL (the number after `leagueId=`).
- **ESPN, private league**: run `python3 update.py --espn-login`. A browser window opens on ESPN; sign in there as you normally would (captchas and email codes work). The script then lists your ESPN football leagues, adds the ones you pick to `leagues.json`, and runs the usual update so they appear on the page. Your password only ever goes into ESPN's own page; what's saved is the two login cookies ESPN uses (`espn_s2` and `SWID`). When ESPN signs you out (every few months, or if the league stops loading with "ESPN refused access"), run `--espn-login` again to refresh them. Keep `leagues.json` private: those cookies work like your ESPN login. They're never written into the page, but the league data is, so don't post `site/index.html` publicly.

  Needs Playwright once: `python3 -m pip install --user playwright && python3 -m playwright install chromium`. You can still fill in `leagues.json` by hand instead (copy `leagues.example.json`, cookies from DevTools → Application → Cookies on espn.com).

Connected leagues are remembered in your browser (local storage), not in any file.

How the league numbers work:

- **Suggested lineup**: the highest-projected legal lineup for the upcoming week from Sleeper's full-PPR projections. Players on bye, Out, Doubtful or on IR are skipped. Rows that differ from your current lineup are highlighted.
- **Projected finishing records**: every remaining regular-season matchup is simulated 5,000 times, using each team's best projected lineup for that week (so bye weeks count). Projections are scaled to your league's scoring using points scored so far, and week-to-week randomness comes from how much scores have actually varied in your league.
- **Roster value**: trades, pickups and position strengths all use one number: a roster's average weekly points from its best lineup, from the upcoming week through Week 17 (so fantasy playoffs count, and bye weeks count as zero). A player is worth what he adds to that, which is how position need comes in: a third good RB adds little if only two RBs can start. Position strengths count only each position's own slots, with FLEX as its own row, so a trade only moves the positions it touches.
- **Suggested trades**: every one-for-one and two-for-one swap with every team is scored, and only trades that raise your number *and* don't lower theirs are shown, so the other team has a reason to say yes. If a trade leaves a team over its roster size, its lowest-value player is assumed dropped.
- **Trade analyzer**: tick players on each side to see both teams' position strengths before and after, and the whole league's power rankings and playoff odds after. The before and after simulations use the same random draws, so differences come from the trade, not luck.
- **Waivers**: available means not on any roster in the league. Each player's upcoming opponent is listed. Suggested pickups test each top free agent against every possible drop on your roster.
- **Matchup**: you and this week's opponent side by side: each team's best projected lineup, projected scores and your chance of winning. The chance comes from the gap between the two projections and how much weekly scores have varied in your league. In basketball, a week already under way keeps the points scored so far and only the remaining days are uncertain. The same matchup sits at the top of Overview.
- **Team rosters**: click any team name (power rankings, position strengths, projected records, matchups) for its record, power rank, playoff odds, this week's opponent, position ranks and full roster, with a button to start a trade with that team.
- **Power rankings**: a 0–100 score that blends all-play record and win-loss record with projected rest-of-season roster strength. Results get more weight as the season goes on, up to 60% after six games.

## Games: Blind Rank

The **Games** tab on both pages. Pick a position and a board (this week, rest of season or dynasty), and five players from the top of that board arrive one at a time; place each in a 1–5 ladder before you see the next. Every pair you put in the wrong order costs the gap between their real ranks, so swapping #9 and #10 costs 1 while putting #20 above #10 costs 10. The score is 100% minus your cost as a share of the worst possible order (fully reversed = 0%). Only a perfect order scores 100% (any mistake caps it at 99%) and only a fully reversed one scores 0%. Cards show age, team and injury status, but no stats. Best scores are remembered per position in your browser. Keys 1–5 place the current player.

## Games: Draft

Draft a standard starting lineup, one pick a round: 9 in football (QB, 2 RB, 2 WR, TE, FLEX, K, D/ST) and 10 in basketball (PG, SG, SF, PF, C, G, F, 3 UTIL, ESPN's default). Each round offers five players from the tier you'd be picking in during a 12-team snake draft: round 1 from about the top 30, round 2 from about picks 13–42, and so on, with everyone ranked above the tier treated as taken by other teams. That keeps the five close in value, so there's rarely an obvious pick. You get one respin per draft to swap a round's five for a new set from the same tier. A pick goes into the most specific open spot (a RB fills a RB spot before the FLEX), and a position stops appearing once no open spot can take it. Overall order is the basketball rest-of-season overall board; in football, where there's no overall board, players are ordered by projected points above a typical starter at their position.

The power score compares your lineup's projected points per week with the best and worst lineups you could have built from the sets you picked from (one player per round): 100 is the best possible team from those choices, 0 the worst.

## Games: Who's That?

Five players, one at a time, drawn from the top 150 on the rest-of-season board (football skips kickers and defenses; players with no college on file are left out). You see the face, position and team, and answer three questions: name and college (both boxes suggest matches as you type: "cle" shows Clemson; arrow keys and Enter pick one) and decade drafted (a dropdown). Each player's answers are revealed before the next. The score is correct answers out of 15. "Decade drafted" is the decade of the player's rookie season, worked out from Sleeper's years of experience: the draft year for drafted players, the year an undrafted player entered the league.

## Hosted on GitHub Pages

`.github/workflows/update-site.yml` rebuilds both pages every day at 11 am US Eastern on GitHub's servers and publishes them with GitHub Pages, so your computer doesn't need to be on. The football page is the site's front page; basketball is `basketball.html`.

- **Run it now:** the repository's **Actions** tab → **Update site** → **Run workflow**.
- **Timing:** GitHub schedules run on UTC, so there are two triggers (15:00 and 16:00 UTC) and the job skips whichever isn't 11 am in New York that day. Runs can start a few minutes late when GitHub is busy.
- **What's uploaded:** the code only. `site/` and `data/` are built fresh on GitHub (`data/` is carried between runs in the Actions cache, so past seasons download only once), and `leagues.json` is never committed (see `.gitignore`).
- **Private ESPN leagues:** paste the contents of your `leagues.json` into a repository secret named `LEAGUES_JSON` (Settings → Secrets and variables → Actions). The site is public, so the league data it fetches will be visible to anyone with the link; your cookies stay in the secret.
- **It's public:** anyone with the link can open the site, and it republishes rankings collected from other sites whose terms restrict scraping. Delete the repository or turn off Pages (Settings → Pages) to take it down.

## Things to know

- These are public but unofficial endpoints and pages. They can change without notice, and scraping may be restricted by a site's terms. Keep it to personal use and the once-a-week schedule.
- The fetchers were written without being able to reach those sites, so the first live run is the real test. Failures print to the terminal, and the page footer names any source that was unavailable. If one breaks, its adapter in `rankings/sources.py` is the only place to fix.
- The season opener is calculated as the Thursday after Labor Day, which gives September 10 for 2026.
- If two sites spell a player differently and he shows up twice, add a line to `ALIASES` in `rankings/aggregate.py`. ESPN roster players are matched by ESPN id where Sleeper has one, otherwise by name using the same rules.
- Injuries come from ESPN's league-wide injury report: status, ESPN's expected return date and the latest practice note. The **chance to play** next to Questionable and Doubtful players is this site's own estimate, not an official number: 70% for Questionable and 15% for Doubtful, +15 for a full practice and −20 for a missed one, capped at 5% when ESPN expects the player back after the game. Tune it in `chance_to_play` in `rankings/players.py`.
- Player faces and team logos load from Sleeper's image server when the page is open, so they need an internet connection; offline, initials show instead.
- Game logs, projections and injury statuses are a snapshot from the last `update.py` run. League rosters, scores and matchups are fetched live when you open the tab (except private ESPN leagues, which are as of the last run).
- On Apple's built-in Python, KeepTradeCut is fetched with the system `curl`, because that Python can't make the TLS 1.3 connection the site requires.

## Adding a source or changing the board

- New source: write a function in `rankings/sources.py` returning rows with `name`, `pos`, `team`, and either `score` (higher is better) or `rank`, then add it to `source_registry`.
- Players shown per position: `LIMITS` in `rankings/aggregate.py`.
- The page itself (HTML, CSS and JavaScript) is `rankings/template.html`.
- Tests: `python3 -m unittest discover -s tests -t .`
