# Likvido github action for releasing NuGet packages

Builds, packs and pushes a NuGet package to nuget.org using
[Trusted Publishing](https://learn.microsoft.com/en-us/nuget/nuget-org/trusted-publishing) (OIDC).
No long-lived API key is stored in repository or organization secrets - nuget.org issues a
short-lived key at publish time, valid for one hour.

## Usage

```yaml
jobs:
  nuget:
    runs-on: ubuntu-latest

    permissions:
      contents: read    # required by actions/checkout
      id-token: write   # required to request the OIDC token

    steps:
      - name: Checkout
        uses: actions/checkout@v7

      - name: Setup .NET
        uses: actions/setup-dotnet@v6
        with:
          dotnet-version: 10.x

      - name: Publish NuGet
        uses: likvido/action-nuget@v2
        with:
          project: src/Likvido.Project/Likvido.Project.csproj
          nuget-user: ${{ vars.NUGET_USER }}
```

### The `permissions` block is required

`id-token: write` cannot be set inside a composite action, so it must be declared in the calling
job. Note that specifying **any** `permissions` key sets every unlisted scope to `none`, so
`contents: read` has to be listed as well or `actions/checkout` will fail.

### Prerequisite: a Trusted Publishing policy

Each repository needs its own policy, registered on nuget.org under the account that owns the
packages (**Package Owner**). Policies match on repository owner + repository + workflow file name:

| Field            | Value                                   |
| ---------------- | --------------------------------------- |
| Package Owner    | the nuget.org account owning the package |
| CI/CD Provider   | `GitHub Actions`                        |
| Repository Owner | `Likvido`                               |
| Repository       | the repository name                     |
| Workflow File    | `nuget.yml` (file name only, no path)   |
| Environment      | blank - see below                       |

Leave **Environment** blank unless the calling job sets `environment:`, in which case the policy
must carry that exact environment name or the token exchange will not match. No Likvido publishing
workflow uses an environment today.

The `nuget-user` input must be the same account as the policy's **Package Owner**.

## Versions

| Version | Authentication                                       |
| ------- | ---------------------------------------------------- |
| `v3`    | As `v2`, plus the `api-compatibility` action          |
| `v2`    | Trusted Publishing (OIDC) via `nuget-user`            |
| `v1`    | Long-lived API key via `nuget-key` - **deprecated**   |

`v1` remains available while repositories migrate, but it depends on a long-lived API key and
should not be used for new workflows.

## API compatibility check

`api-compatibility` is a second action in this repository. It packs each project with .NET
[package validation](https://learn.microsoft.com/en-us/dotnet/fundamentals/apicompat/package-validation/overview)
and compares its public API with the newest version of its package listed on nuget.org. The version
in the pull request plays no part, so the result is the same before and after a version raise.

- No breaking change: the job succeeds.
- A breaking change (a `CP0xxx` or `PKVxxx` diagnostic): the job fails, with each diagnostic as an
  annotation and all of them in the job summary.
- A package with no listed version on nuget.org: the job succeeds and says there was nothing to
  compare with.
- A project that does not pack, or nuget.org that cannot be read: the job fails without a
  diagnostic.

Run it on `pull_request`, in a job named `api-compatibility`, with the same project paths as
`nuget.yml`:

```yaml
name: API compatibility

on:
  pull_request:

permissions:
  contents: read

jobs:
  api-compatibility:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v7
        with:
          persist-credentials: false

      - name: Setup .NET
        uses: actions/setup-dotnet@v6
        with:
          dotnet-version: 10.x

      - name: Compare the public API with nuget.org
        uses: likvido/action-nuget/api-compatibility@v3
        with:
          projects: |
            src/Likvido.Project/Likvido.Project.csproj
```

A breaking change needs a new major version, which a person merges, or the old API kept. The check
stays failed until that major is on nuget.org, since that is what it compares with.

# Releasing new version

Either create the new release + new version tag directly in the Github UI, or create it like this:

1. Commit and push your changes
2. Create a new tag: `git tag -a -m "Description of this release" <version>`
3. Push the tag: `git push --follow-tags`

## Example

```
git tag -a -m "First version of nuget action" v1
git push --follow-tags
```
