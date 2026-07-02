-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — retire the P5 rule engine + subscription notifications
--
-- Runs after 0018. Visual flows (0018) are now the only automation/notification
-- policy: rules, their execution log, channel subscriptions, and the in-app
-- notification center are removed. Web-push subscriptions stay (flow push nodes
-- target them). Existing DBs: run this file manually before restarting the backend.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

DROP TABLE IF EXISTS `rules`;
DROP TABLE IF EXISTS `rule_executions`;
DROP TABLE IF EXISTS `notification_subscriptions`;
DROP TABLE IF EXISTS `notifications`;
