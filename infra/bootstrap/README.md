# Legacy WarnWatcher backend

This stack created WarnWatcher's original application-specific state bucket and DynamoDB lock table.

The active WarnWatcher state was migrated to the shared account backend on 2026-08-28. Do not apply or destroy this legacy bootstrap stack. Its bucket and lock table are retained temporarily as rollback resources.

The shared account backend is managed from `/Users/bret/Development/aws-account-infra`.

