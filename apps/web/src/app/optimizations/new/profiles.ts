export type OptimizationProfileKey = "perfect" | "realistic" | "stress" | "other";

export type OptimizationProfile = {
  key: OptimizationProfileKey;
  title: string;
  subtitle: string;
  fromTo: string;
  trials: string;
  initialCapital: string;
  feeMaker: string;
  feeTaker: string;
  takerSlippage: string;
  slippageSmall: string;
  slippageMedium: string;
  modelSqrtLimit: string;
  fill: "perfect" | "simulated" | "custom";
  limitFillTimeout: string;
  minQtyThreshold: string;
  minQtyCheck: boolean;
  datasetEstimate?: string;
  runtimeEstimate?: string;
};

export const optimizationProfiles: OptimizationProfile[] = [
  {
    key: "perfect",
    title: "1. Perfect-fill",
    subtitle: "Comparison only, no fees or slippage.",
    fromTo: "2025-07-01:2026-06-15",
    trials: "100",
    initialCapital: "10000",
    feeMaker: "0",
    feeTaker: "0",
    takerSlippage: "0",
    slippageSmall: "0",
    slippageMedium: "0",
    modelSqrtLimit: "1.0",
    fill: "perfect",
    limitFillTimeout: "1",
    minQtyThreshold: "0",
    minQtyCheck: false,
    datasetEstimate: "349 days / about 502,560 1m candles",
    runtimeEstimate: "One EUR/USD group with 100 trials should finish in about 5 minutes or faster.",
  },
  {
    key: "realistic",
    title: "2. Realistic",
    subtitle: "Baseline optimizer assumptions.",
    fromTo: "2025-07-01:2026-06-15",
    trials: "500",
    initialCapital: "10000",
    feeMaker: "0.0002",
    feeTaker: "0.0006",
    takerSlippage: "0.0005",
    slippageSmall: "0.0002",
    slippageMedium: "0.001",
    modelSqrtLimit: "1.0",
    fill: "simulated",
    limitFillTimeout: "5",
    minQtyThreshold: "0.01",
    minQtyCheck: true,
  },
  {
    key: "stress",
    title: "3. Stress",
    subtitle: "Conservative robustness check.",
    fromTo: "2025-07-01:2026-06-15",
    trials: "500",
    initialCapital: "10000",
    feeMaker: "0.0005",
    feeTaker: "0.0010",
    takerSlippage: "0.0015",
    slippageSmall: "0.0008",
    slippageMedium: "0.003",
    modelSqrtLimit: "0.7",
    fill: "simulated",
    limitFillTimeout: "10",
    minQtyThreshold: "0.02",
    minQtyCheck: true,
  },
  {
    key: "other",
    title: "4. Other",
    subtitle: "Open all fields and enter custom values.",
    fromTo: "custom",
    trials: "25",
    initialCapital: "10000",
    feeMaker: "0.001",
    feeTaker: "0.001",
    takerSlippage: "not supported",
    slippageSmall: "0.0005",
    slippageMedium: "0.001",
    modelSqrtLimit: "not supported",
    fill: "custom",
    limitFillTimeout: "30",
    minQtyThreshold: "not supported",
    minQtyCheck: true,
  },
];
