import hashlib
import logging
import textwrap
import traceback
from typing import Any, Dict, List, Union

import ipyvuetify as v
import pygments
import pymdownx.highlight
import pymdownx.superfences
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

import solara
import solara.components.applayout

logger = logging.getLogger(__name__)

html_no_execute_enabled = "<div><i>Solara execution is not enabled</i></div>"


@solara.component
def ExceptionGuard(children=[]):
    exception, clear_exception = solara.use_exception()
    if exception:
        solara.Error(f"Oops, an error occurred: {str(exception)}")
        with solara.Details("Exception details"):
            error = "".join(traceback.format_exception(None, exception, exception.__traceback__))
            solara.Preformatted(error)
    else:
        if len(children) == 1:
            return children[0]
        else:
            solara.Column(children=children)


def _run_solara(code):
    ast = compile(code, "markdown", "exec")
    local_scope: Dict[Any, Any] = {}
    exec(ast, local_scope)
    app = None
    if "app" in local_scope:
        app = local_scope["app"]
    elif "Page" in local_scope:
        Page = local_scope["Page"]
        app = solara.components.applayout._AppLayoutEmbed(children=[ExceptionGuard(children=[Page()])])
    else:
        raise NameError("No Page of app defined")
    box = v.Html(tag="div")
    box, rc = solara.render(app, container=box)
    widget_id = box._model_id
    return (
        '<div class="solara-markdown-output v-card v-sheet elevation-7">'
        f'<jupyter-widget widget="IPY_MODEL_{widget_id}">loading widget...</jupyter-widget>'
        '<div class="v-messages">Live output</div></div>'
    )


def _markdown_template(html, style=""):
    return (
        """
<template>
    <div class="solara-markdown rendered_html jp-RenderedHTMLCommon" style=\""""
        + style
        + """\">"""
        + html
        + """</div>
</template>

<script>
module.exports = {
    mounted() {
        mermaid.init()
        this.$el.querySelectorAll("a").forEach(a => this.setupRouter(a))
        window.md = this.$el
    },
    methods: {
        setupRouter(a) {
            let href = a.attributes['href'].value;
            if(href.startsWith("./")) {
                // TODO: should we really do this?
                href = location.pathname + href.substr(1);
                a.attributes['href'].href = href;
                // console.log("change href to", href);
            }
            if(href.startsWith("./") || href.startsWith("/")) {
                // console.log("connect link with href=", href, "to router")
                a.onclick = e => {
                    console.log("clicked", href)
                    if(href.startsWith("./")) {
                        solara.router.push(href);
                    } else {
                        solara.router.push(href);
                    }
                    e.preventDefault()
                }
            } else if(href.startsWith("#")) {
                // console.log("connect anchor with href=", href, "to custom javascript due to using <base>")
                href = location.pathname + href;
                a.attributes['href'].value = href;
            } else {
                console.log("href", href, "is not a local link")
            }
        }
    },
    updated() {
        // if the html gets update, re-run mermaid
        mermaid.init()
    }
}
</script>
    """
    )


def _highlight(src, language, unsafe_solara_execute, extra, *args, **kwargs):
    """Highlight a block of code"""

    run_src_with_solara = False
    if language == "solara":
        run_src_with_solara = True
        language = "python"

    lexer = get_lexer_by_name(language)
    formatter = HtmlFormatter()
    html = pygments.highlight(src, lexer, formatter)

    if run_src_with_solara:
        if unsafe_solara_execute:
            html_widget = _run_solara(src)
            return html + html_widget
        else:
            return html + html_no_execute_enabled
    else:
        return html


@solara.component
def MarkdownIt(md_text: str, highlight: List[int] = [], unsafe_solara_execute: bool = False):
    md_text = textwrap.dedent(md_text)

    from markdown_it import MarkdownIt as MarkdownItMod
    from mdit_py_plugins import container, deflist  # noqa: F401
    from mdit_py_plugins.footnote import footnote_plugin  # noqa: F401
    from mdit_py_plugins.front_matter import front_matter_plugin  # noqa: F401

    def highlight_code(code, name, attrs):
        return _highlight(code, name, unsafe_solara_execute, attrs)

    md = MarkdownItMod(
        "js-default",
        {
            "html": True,
            "typographer": True,
            "highlight": highlight_code,
        },
    )
    md = md.use(container.container_plugin, name="note")
    html = md.render(md_text)
    hash = hashlib.sha256((html + str(unsafe_solara_execute) + repr(highlight)).encode("utf-8")).hexdigest()
    return v.VuetifyTemplate.element(template=_markdown_template(html)).key(hash)


@solara.component
def Markdown(md_text: str, unsafe_solara_execute=False, style: Union[str, Dict, None] = None):
    """Renders markdown text

    Renders markdown using https://python-markdown.github.io/

    ## Arguments

     * `md_text`: The markdown text to render
     * `unsafe_solara_execute`: If True, code marked with language "solara" will be executed. This is potentially unsafe
        if the markdown text can come from user input and should only be used for trusted markdown.
     * `style`: A string or dict of css styles to apply to the rendered markdown.

    """
    import markdown

    md_text = textwrap.dedent(md_text)
    style = solara.util._flatten_style(style)

    def make_markdown_object():
        def highlight(src, language, *args, **kwargs):
            try:
                return _highlight(src, language, unsafe_solara_execute, *args, **kwargs)
            except Exception as e:
                logger.exception("Error highlighting code: %s", src)
                return repr(e)

        return markdown.Markdown(  # type: ignore
            extensions=[
                "pymdownx.highlight",
                "pymdownx.superfences",
                "pymdownx.emoji",
                "toc",  # so we get anchors for h1 h2 etc
            ],
            extension_configs={
                "pymdownx.superfences": {
                    "custom_fences": [
                        {
                            "name": "mermaid",
                            "class": "mermaid",
                            "format": pymdownx.superfences.fence_div_format,
                        },
                        {
                            "name": "solara",
                            "class": "",
                            "format": highlight,
                        },
                    ],
                },
            },
        )

    md = solara.use_memo(make_markdown_object, dependencies=[unsafe_solara_execute])
    html = md.convert(md_text)
    # if we update the template value, the whole vue tree will rerender (ipvue/ipyvuetify issue)
    # however, using the hash we simply generate a new widget each time
    hash = hashlib.sha256((html + str(unsafe_solara_execute)).encode("utf-8")).hexdigest()
    return v.VuetifyTemplate.element(template=_markdown_template(html, style)).key(hash)
