"""Spin 结构回归：#due-spin「加载中…」常显 bug。

多余的一层裸 <div> 会让 ds/antd-lite.css 的直子选择器
（.ant-spin-nested-loading > .ant-spin { display:none } / > .ant-spin.ant-spin-spinning
{ display:block }）失配，spinner 变成常显的静态块。这里用 stdlib html.parser
校验模板结构：每个 .ant-spin-nested-loading 的 .ant-spin / .ant-spin-container
都必须是直接子级，且初始仅 #page-spin 处于 spinning（boot() 加载完会关掉）。
"""

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")

VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input",
     "link", "meta", "param", "source", "track", "wbr"}
)


class StructureParser(HTMLParser):
    """记录 .ant-spin / .ant-spin-container 相对 .ant-spin-nested-loading 的层级。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.spins = []
        self.nested_loadings = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        attrs_map = dict(attrs)
        element = {
            "tag": tag,
            "id": attrs_map.get("id") or "",
            "classes": frozenset((attrs_map.get("class") or "").split()),
            "attrs": attrs_map,
            "parent": self.stack[-1] if self.stack else None,
        }
        self.stack.append(element)
        if "ant-spin-nested-loading" in element["classes"]:
            element["has_direct_spin"] = False
            element["has_direct_container"] = False
            element["direct_spin_spinning"] = None
            element["direct_spin_aria_hidden"] = None
            self.nested_loadings.append(element)
        if "ant-spin" in element["classes"]:
            self.spins.append(element)
        parent = element["parent"]
        if parent is not None and "ant-spin-nested-loading" in parent["classes"]:
            if "ant-spin" in element["classes"]:
                parent["has_direct_spin"] = True
                parent["direct_spin_spinning"] = "ant-spin-spinning" in element["classes"]
                parent["direct_spin_aria_hidden"] = attrs_map.get("aria-hidden")
            if "ant-spin-container" in element["classes"]:
                parent["has_direct_container"] = True

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                return


def parse_structure():
    parser = StructureParser()
    parser.feed(HTML)
    parser.close()
    return parser


def test_template_has_expected_spin_hosts():
    parser = parse_structure()
    assert parser.nested_loadings, "模板里找不到 .ant-spin-nested-loading"
    assert {host["id"] for host in parser.nested_loadings} == {"page-spin", "due-spin"}


def test_every_spin_lives_directly_inside_nested_loading():
    parser = parse_structure()
    assert parser.spins, "模板里找不到 .ant-spin"
    for spin in parser.spins:
        parent = spin["parent"]
        assert parent is not None and "ant-spin-nested-loading" in parent["classes"], (
            f".ant-spin（#{spin['id'] or spin['tag']}）必须直接位于 .ant-spin-nested-loading 内"
        )


def test_nested_loading_has_direct_child_spin_and_container():
    parser = parse_structure()
    for host in parser.nested_loadings:
        assert host["has_direct_spin"], (
            f"#{host['id']} 的 .ant-spin 被多余标签包住，必须是 .ant-spin-nested-loading 的直接子级"
        )
        assert host["has_direct_container"], (
            f"#{host['id']} 的 .ant-spin-container 必须是 .ant-spin-nested-loading 的直接子级"
        )


def test_only_page_spin_initially_spinning():
    parser = parse_structure()
    for host in parser.nested_loadings:
        if host["id"] == "page-spin":
            assert host["direct_spin_spinning"] is True
            assert 'setSpin(document.getElementById("page-spin"), false)' in HTML
        else:
            assert host["direct_spin_spinning"] is False, (
                f"#{host['id']} 初始不应处于 spinning（静态 spinner 会常显）"
            )
            assert host["direct_spin_aria_hidden"] == "true"


def test_set_spin_targets_direct_children():
    assert '":scope > .ant-spin"' in HTML
    assert '":scope > .ant-spin-container"' in HTML
    assert ":scope > div > .ant-spin" not in HTML


def test_page_local_css_hides_non_spinning_nested_spin():
    assert ".ant-spin-nested-loading .ant-spin:not(.ant-spin-spinning)" in HTML
