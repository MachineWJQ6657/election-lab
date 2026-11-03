// Conditional ballot accounting, NOT a calibrated election-win probability.
// Preference and final turnout are explicit user assumptions, never inferred
// from registration, ethnicity, or ballot-request counts.
export function earlyVoteScenario(input: {
  reportedBallots: number; finalTurnout: number; exposure: number;
  earlyDemShare: number; remainingDemShare: number;
}) {
  const { reportedBallots, finalTurnout, exposure, earlyDemShare, remainingDemShare } = input;
  if (![reportedBallots, finalTurnout, exposure, earlyDemShare, remainingDemShare].every(Number.isFinite)) throw new Error("Use finite scenario inputs");
  if (reportedBallots < 0 || finalTurnout <= 0 || reportedBallots > finalTurnout) throw new Error("Assumed final turnout must cover reported ballots");
  if ([exposure, earlyDemShare, remainingDemShare].some((n) => n < 0 || n > 1)) throw new Error("Shares and exposure must be between 0 and 1");
  const includedEarly = reportedBallots * exposure;
  const remaining = finalTurnout - includedEarly;
  const earlyWeight = includedEarly / finalTurnout;
  const demShare = earlyWeight * earlyDemShare + (1 - earlyWeight) * remainingDemShare;
  return {
    includedEarly, remaining, earlyWeight, demShare,
    demMargin: 100 * (2 * demShare - 1),
    requiredRemainingDemShare: remaining === 0 ? null : (finalTurnout / 2 - includedEarly * earlyDemShare) / remaining,
  };
}
