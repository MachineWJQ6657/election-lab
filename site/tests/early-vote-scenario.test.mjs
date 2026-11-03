import test from "node:test";
import assert from "node:assert/strict";
import { earlyVoteScenario } from "../lib/early-vote-scenario.ts";

const base = {reportedBallots:400,finalTurnout:1000,exposure:1,earlyDemShare:.6,remainingDemShare:.5};
test("reported ballots have an explicit count-based weight, not party-registration votes",()=>{
  const r=earlyVoteScenario(base);
  assert.equal(r.earlyWeight,.4);
  assert.ok(Math.abs(r.demShare-.54)<1e-12);
  assert.ok(Math.abs(r.requiredRemainingDemShare-260/600)<1e-12);
});
test("exposure zero recovers remaining-electorate assumptions and equal preferences are invariant",()=>{
  assert.equal(earlyVoteScenario({...base,exposure:0}).demShare,.5);
  assert.ok(Math.abs(earlyVoteScenario({...base,earlyDemShare:.54,remainingDemShare:.54}).demMargin-8)<1e-10);
  assert.ok(earlyVoteScenario({...base,reportedBallots:600}).earlyWeight>earlyVoteScenario(base).earlyWeight);
});
test("all ballots included and impossible assumptions are handled explicitly",()=>{
  assert.equal(earlyVoteScenario({...base,reportedBallots:1000}).requiredRemainingDemShare,null);
  for (const change of [{reportedBallots:1001},{finalTurnout:0},{exposure:1.1},{earlyDemShare:NaN},{remainingDemShare:-1}]) assert.throws(()=>earlyVoteScenario({...base,...change}));
});
test("sensitivity follows ballot exposure rather than inventing election-win odds",()=>{
  const a=earlyVoteScenario(base);
  const b=earlyVoteScenario({...base,earlyDemShare:base.earlyDemShare+.01});
  assert.ok(Math.abs(b.demMargin-a.demMargin-2*a.earlyWeight)<1e-10);
  assert.ok(earlyVoteScenario({...base,exposure:.5}).demShare<a.demShare);
  assert.ok(!("winProbability" in a));
  for (const early of [0,.25,.5,.75,1]) for (const remaining of [0,.25,.5,.75,1]) {
    const result=earlyVoteScenario({...base,earlyDemShare:early,remainingDemShare:remaining});
    assert.ok(result.demShare>=Math.min(early,remaining)-1e-12);
    assert.ok(result.demShare<=Math.max(early,remaining)+1e-12);
  }
});
