R:R filter must not mark trials as FAILED.

Do not sample stop_loss_points and take_profit_points independently and then fail invalid combinations.

Instead:
1. Sample stop_loss_points first.
2. Sample risk_reward_ratio between 1.5 and 4.0.
3. Derive take_profit_points = round_to_step(stop_loss_points * risk_reward_ratio, 50).
4. Store both values in config_overrides.theoretical_trade.
5. Invalid combinations should be impossible.
6. If a combination somehow cannot be created, use TrialPruned, not FAILED.
7. Failed trial count should represent real code/runtime errors only.