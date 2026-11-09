CREATE TABLE `rag_knowledge_bases` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`route_url` text NOT NULL,
	`description` text,
	`is_active` integer DEFAULT false NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `rag_knowledge_bases_active_uidx` ON `rag_knowledge_bases` (`is_active`) WHERE "rag_knowledge_bases"."is_active" = 1;