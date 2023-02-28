# Likvido github action for releasing NuGet packages

```
jobs:
  nuget:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v3

      - name: Setup .NET
        uses: actions/setup-dotnet@v3
        with:
          dotnet-version: 7.x

      - name: Publish NuGet
        uses: likvido/action-nuget@v1
        with:
          nuget-key: ${{ secrets.NUGET_API_KEY }}
          project: src/Likvido.Project.csproj
```


# Releasing new version

Either create the new release + new version tag directly in the Github UI, or create it like this:

1. Commit and push your changes
2. Create a new tag: `git tag -a -m "Description of this release" <actionName>-<version>`
3. Push the tag: `git push --follow-tags`

## Example

```
git tag -a -m "First version of nuget action" v1
git push --follow-tags
```
