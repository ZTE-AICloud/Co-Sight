CREATE TABLE `agent_proxy_configs` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`description` text,
	`agent_type` text NOT NULL,
	`endpoint` text,
	`enabled` integer NOT NULL,
	`is_default` integer NOT NULL,
	`max_iterations` integer NOT NULL,
	`parallelism` integer NOT NULL,
	`timeout_seconds` integer NOT NULL,
	`memory_enabled` integer NOT NULL,
	`condensation_enabled` integer NOT NULL,
	`security_analyzer` text NOT NULL,
	`token_ref` text,
	`extra` text NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `app_state` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text NOT NULL,
	`updated_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `experts` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`author` text NOT NULL,
	`description` text NOT NULL,
	`avatar_url` text,
	`tags` text NOT NULL,
	`use_count` integer NOT NULL,
	`is_preset` integer NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `experts_use_count_idx` ON `experts` (`use_count`);--> statement-breakpoint
CREATE INDEX `experts_created_at_idx` ON `experts` (`created_at`);--> statement-breakpoint
CREATE INDEX `experts_is_preset_idx` ON `experts` (`is_preset`);--> statement-breakpoint
CREATE INDEX `experts_name_idx` ON `experts` (`name`);--> statement-breakpoint
CREATE TABLE `model_configs` (
	`id` text PRIMARY KEY NOT NULL,
	`provider` text NOT NULL,
	`label` text NOT NULL,
	`base_url` text,
	`model_name` text NOT NULL,
	`api_key_ref` text,
	`is_active` integer NOT NULL,
	`temperature` real NOT NULL,
	`top_p` real NOT NULL,
	`max_output_tokens` integer,
	`context_window` integer,
	`timeout_seconds` integer NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `workspaces` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`directory` text,
	`default_model_id` text,
	`default_agent_id` text,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL
);
