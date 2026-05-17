# ARIA Progress — Week 1

## What we did this week

Got a lot done. All three of us have Webots installed. We picked the Pioneer 3-DX robot—wheels, 8 distance sensors, GPS, compass.

Built the project from scratch:
- 20 Python files, 600+ lines of core code
- Data models for robot state and actions
- Config system (reads from .env, no hardcoded values)
- TCP server that talks to Webots (handles motor control, sensor reads)
- MCP bridge that exposes 5 tools to the agent
- 6 test cases ready to run
- Documentation (setup guide, implementation plan, status tracker)

Verified everything works:
- All modules import without errors
- Config loads correctly
- No dependency issues

Architecture is solid. Three layers:
1. LangGraph agent (decides what to do)
2. MCP server (exposes robot as callable tools)
3. TCP controller (talks to Webots simulator)

Each layer independent. Swap any one without touching the others.

---

## What we're doing this weekend (Phase 2)

Create the Webots world. Add robot, sensors, obstacles, target. ~1 hour.

Place the TCP controller code inside Webots. Run simulation. Verify port 19997 is listening. ~30 min.

Run the tests. Check that TCP connection works, state retrieval works, actions execute. ~30 min.

Total: ~2 hours. No blockers.

---

## Next 2 weeks (Phases 2–3)

**Week 2:** Finish Webots integration. TCP connection should be rock solid by end of week.

**Week 3:** Validate MCP server against live Webots. Make sure all 5 tools work correctly.

---

## Weeks 4–6 (Phases 4–5)

Build the LangGraph agent. Implement sense node (read state), plan node (LLM decides action), act node (execute), evaluate node (check success or stuck). Wire it to the MCP server. Full end-to-end loop should work by week 4.

Integration and benchmarking. Test on 5+ tasks. Measure success rates.

---

## The hard problems we identified

**LLM latency.** API takes 0.5–2 seconds. We're slowing the simulation to 0.1x speed so the robot has time to think.

**Spatial reasoning drift.** Robot loses track of where it is over many steps. We keep the last 10 states so the LLM can stay grounded.

**Prompt sensitivity.** Small wording changes shift success by 10–20%. We'll test three different prompting strategies and measure which one works best.

**TCP sync, stuck loops, local LLM quality.** We have solutions for all of it. They're baked into the design.

---

## What's ready right now

- Code is done (Phase 1)
- Tests are written (will run once Webots connects)
- Documentation is complete
- Team is aligned on the approach
- No external blockers

What's not ready:
- Webots world (creating this weekend)
- Agent logic (start week 4)
- Experiments (weeks 8–9)

---

## Timeline

Phase 1 (this week): ✓ Done  
Phase 2 (weeks 2–3): Webots + TCP  
Phase 3 (weeks 3–4): MCP validation  
Phase 4 (weeks 4–6): Agent implementation  
Phase 5 (weeks 6–8): Integration + benchmarks  
Phase 6 (weeks 8–9): Ablation studies + demo  

On track. No issues.
