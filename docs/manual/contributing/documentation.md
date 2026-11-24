# Writing documentation

The manual is the Markdown files under `docs/manual/`. Zensical turns them into
this site, and they must also read well on GitHub.

## See your changes

```bash
./gpgpu docs site:serve    # http://127.0.0.1:8000, rebuilt on every edit
./gpgpu docs site:build    # the static site, in site/
```

`site:serve` runs until you press Ctrl-C. To use another port:

```bash
./gpgpu --set docs.site.port=8001 docs site:serve
```

`site:build` fails on any of these:

- a link to a page or a heading that does not exist;
- an image or another local file that does not exist;
- a page that `mkdocs.yml` does not list in `nav`, or lists twice;
- a `nav` entry without a page.

## Add a page

1. Create the Markdown file in its chapter's folder, with one `#` title.
2. Add it to `nav` in `mkdocs.yml`, at the place a reader should find it.
3. Run `./gpgpu docs site:build`.

## Where a document goes

| It is about | Put it in |
| --- | --- |
| Using or changing the project | `docs/manual/` |
| An investigation or a decision, kept as history | `docs/notes/` |
| One folder, for whoever edits it | A `README.md` in that folder |

## Rules

- **Notes** are block quotes that start with `**Note:**`. GitHub shows `!!!`
  admonitions as plain text, and Zensical does the same to GitHub's `[!NOTE]`.
- **Link to pages** with a relative path, such as `../index.md`. A page cannot
  link to a file outside `docs/manual/`: write its path as code instead.
- **Blocks inside a list item** are indented by four spaces. GitHub accepts
  fewer, but Zensical then ends the list.
- **Diagrams** are Mermaid code blocks. GitHub draws them too. Keep labels
  short: a wide diagram is shrunk to the width of the text.
- **Planned features** appear only as a short note where the reader would look
  for them.
- **Do not copy values** that the RTL or the configuration owns, such as sizes
  and addresses. Name the option or the constant.
- **No machine or account names.** Use placeholders, such as `user@board-host`.
