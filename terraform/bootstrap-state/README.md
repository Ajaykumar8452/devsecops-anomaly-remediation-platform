# Terraform state bucket bootstrap

This Terraform root creates only the S3 bucket used for Terraform state. It
does not create networking, IAM, EC2, EBS, k3s, or application resources.

## Local state first

This root intentionally has no backend block. Terraform therefore uses its
default local backend while creating the bucket. This avoids a circular
dependency: the remote state bucket must exist before Terraform can store state
in that bucket. Local state can contain sensitive values; protect it and keep
it out of Git.

The configuration requires Terraform `>= 1.10.0, < 2.0.0` for compatibility
with native S3 lockfiles and the HashiCorp AWS provider `~> 6.0`. Keep the
generated `.terraform.lock.hcl` under version control to record the selected
provider build.

## Bootstrap sequence

1. Configure AWS authentication outside source code, for example through an
   approved AWS profile, environment credential provider, or federated
   temporary credentials. Do not add access keys to `.tf`, `.tfvars`, or
   backend configuration files.
2. Copy `terraform.tfvars.example` to `terraform.tfvars` and choose a globally
   unique S3 bucket name. The example file is ignored by Git; the example itself
   remains trackable. S3 availability and reserved-name rules are ultimately
   enforced by AWS.
3. From this directory, run the formatting, initialization, validation, and
   provider checks. `terraform init` uses local state because no backend block
   is present:

   ```sh
   terraform fmt -check
   terraform init
   terraform validate
   terraform providers
   terraform plan -out=bootstrap.tfplan
   ```

4. Review the complete plan and its effects. Plans and local state can contain
   sensitive configuration; keep both in a restricted local workspace.
5. Only after explicit human approval, apply the reviewed saved plan:

   ```sh
   terraform apply bootstrap.tfplan
   ```

   No apply is performed by this configuration's validation workflow.
6. Verify the bucket using read-only AWS calls before configuring a backend:

   ```sh
   aws s3api get-bucket-versioning --bucket <bucket-name>
   aws s3api get-bucket-encryption --bucket <bucket-name>
   aws s3api get-public-access-block --bucket <bucket-name>
   aws s3api get-bucket-ownership-controls --bucket <bucket-name>
   aws s3api get-bucket-policy --bucket <bucket-name>
   ```

   Confirm versioning is `Enabled`, default encryption is `AES256`, all four
   public-access-block settings are true, ownership is `BucketOwnerEnforced`,
   and the policy denies requests where `aws:SecureTransport` is false.
7. By default, keep this bootstrap root on local state after it creates the
   bucket. Do not automatically store the bootstrap root's state in the bucket
   it manages. If a separate review explicitly chooses to migrate bootstrap
   state, only after the bucket checks pass create `backend.tf` in this root
   with a partial backend declaration:

   ```hcl
   terraform {
     backend "s3" {}
   }
   ```

   Copy `backend.hcl.example` to `backend.hcl`, set its bucket name to the
   verified bucket, and keep the backend configuration free of credentials.
   Its key must remain separate from every other Terraform root. Backend
   settings cannot use ordinary Terraform input variables.
8. Back up the original local `terraform.tfstate` to an encrypted, access-
   restricted recovery location outside the repository. Record its SHA-256 and
   retain it until remote state is verified. Do not place the recovery copy in
   Git or a shared unprotected folder.
9. Only for that separately approved bootstrap-state migration, migrate the
   local state:

   ```sh
   terraform init -migrate-state -backend-config=backend.hcl
   ```

   Review Terraform's migration prompt and confirm the destination is the
   expected bucket, key, and region.
10. Verify that the state can be read from the configured backend and that
    Terraform recognizes the existing bucket without proposing its recreation.
    Confirm native locking by running an approved, non-destructive operation
    with locking enabled and verifying lock acquisition and release. Retain the
    protected local recovery copy until both checks pass.

The bucket has `prevent_destroy = true` and `force_destroy = false`. These
settings reduce accidental deletion risk; they do not replace versioning,
restricted IAM permissions, backups, or a reviewed recovery procedure. The
bucket policy enforces TLS for bucket and object operations. SSE-S3 is enabled
by default, and S3 Block Public Access plus bucket-owner-enforced ownership are
configured.

The backend example stores this bootstrap root at
`terraform/bootstrap-state/terraform.tfstate`. Future infrastructure roots
must use separate state keys. The backend example is a template and does not
mean remote state exists before this bucket is provisioned and verified.
