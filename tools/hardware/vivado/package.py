"""Fail-closed IP-XACT validation before publication of a staged Vivado IP.

No Vivado/Tcl runtime dependency and no writes. Invalid packages raise ValueError.
The synthesis/simulation filesets must contain exactly the production inputs the
caller resolved from configuration (memory initialization, RTL, headers), in order.
"""
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

NS = 'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'
N = {'s': NS}
FLOW = Path(__file__).resolve().parent
AXI_PORTS = 'AWADDR AWPROT AWVALID AWREADY WDATA WSTRB WVALID WREADY BRESP BVALID BREADY ARADDR ARPROT ARVALID ARREADY RDATA RRESP RVALID RREADY'.split()


def validate_package(path: str | Path, memory_init: Path, sources: Sequence[Path],
                     headers: Sequence[Path]) -> None:
    """Require portable production sources, VLNV and decoded 64-KiB ABI.

    *memory_init* comes first, then *sources* in compile order; *headers* is the
    subset of *sources* packaged as include files.
    """
    root = Path(path).resolve(strict=True)
    try:
        component = ET.parse(root / 'component.xml').getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f'Invalid component.xml: {exc}') from exc

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def text(node, tag):
        return node.findtext('s:' + tag, default='', namespaces=N).strip()

    def named(node, query):
        result = {}
        for item in node.findall(query, N):
            name = text(item, 'name')
            require(name and name not in result, f'Duplicate or missing name: {query}')
            result[name] = item
        return result

    def parameters(node):
        return {name: text(item, 'value') for name, item in named(node, 's:parameters/s:parameter').items()}

    def number(value):
        try:
            return int(value, 16 if value.lower().startswith('0x') else 10)
        except ValueError as exc:
            raise ValueError(f'Invalid numeric metadata: {value!r}') from exc

    require(component.tag == f'{{{NS}}}component', 'Unsupported IP-XACT namespace')
    require(tuple(text(component, k) for k in ('vendor','library','name','version')) ==
            ('user.org','user','gpgpu_axi','1.0'), 'Wrong VLNV')
    inputs = [Path(memory_init), *map(Path, sources)]
    order = [p.name for p in inputs]
    require(len(set(order)) == len(order), 'Production inputs must have unique file names')
    source_files = dict(zip(order, inputs))
    expected = set(source_files)
    memory_name = order[0]
    header_names = [Path(h).name for h in headers]
    require(set(header_names) <= expected, 'Headers must be production sources')
    # Macro name -> defining header, for the explicit-include rule below.
    header_macros = {macro: name for name in header_names
                     for macro in re.findall(r'^`define\s+(\w+)', source_files[name].read_text(), re.M)}
    # Only filesystem-bearing fields are paths: taxonomy, descriptions, VLNVs
    # and parameter identifiers can legitimately start with '/' or contain '..'.
    def local_name(tag):
        return re.sub(r'[^a-z0-9]', '', tag.rsplit('}', 1)[-1].lower())

    def path_field(tag):
        return local_name(tag).endswith(('path', 'paths', 'dir', 'dirs',
                                         'directory', 'directories', 'filename'))

    def metadata_path(value, *, directory=False):
        relative = PurePosixPath(value)
        require(value and not relative.is_absolute() and '..' not in relative.parts and
                '\\' not in value and ':' not in value,
                f'Nonportable metadata path: {value}')
        target = root / value
        require(target.resolve().is_relative_to(root) and
                (target.is_dir() if directory else target.exists()),
                f'Missing or escaping metadata path: {value}')

    # Vivado directory lists may be Tcl-braced/quoted or semicolon-separated.
    # Do not use shell unescaping: it would hide Windows path separators.
    path_items = re.compile(r'\{([^{}]*)\}|"([^"\n]*)"|\'([^\'\n]*)\'|([^\s;{}"\']+)')

    def metadata_field(tag, value):
        directory = local_name(tag).endswith(('dir', 'dirs', 'directory', 'directories'))
        for item in path_items.finditer(value):
            metadata_path(next(v for v in item.groups() if v is not None), directory=directory)
        require(not path_items.sub('', value).strip(' ;'), f'Invalid metadata path list: {value}')

    for element in component.iter():
        if path_field(element.tag):
            metadata_field(element.tag, element.text or '')
            if 'value' in element.attrib:
                metadata_field(element.tag, element.attrib['value'])
        for key, value in element.attrib.items():
            if path_field(key):
                metadata_field(key, value)
        # Also handle named vendor parameters/options such as PROJECT_PATH.
        field = text(element, 'name') or element.get('name', '')
        if field and path_field(field):
            value = element.find('s:value', N)
            if value is not None:
                metadata_field(field, value.text or '')
            elif 'value' in element.attrib:
                metadata_field(field, element.attrib['value'])

    # File-group dependencies are expressions, not plain directory lists. Inspect
    # their literals/path tokens without executing them or treating arithmetic '/'
    # and PARAM_VALUE identifiers as filesystem references.
    dependency_tokens = re.compile(r'"([^"\n]*)"|\'([^\'\n]*)\'|([^\s()\[\]{},;=<>!+*"\']+)')
    for group in component.findall('s:fileSets/s:fileSet', N):
        for element in group.iter():
            values = [v for k, v in element.attrib.items() if local_name(k) == 'dependency']
            if local_name(element.tag) == 'dependency':
                values.append(''.join(element.itertext()))
            for expression in values:
                for token in dependency_tokens.finditer(expression):
                    value = next(v for v in token.groups() if v is not None)
                    quoted = token.group(3) is None
                    file_argument = re.search(r'(?:file_exists|fileexists|directory_exists|direxists)\s*\(\s*$',
                                              expression[:token.start()], re.I)
                    if (file_argument or value == '..' or
                            (value != '/' or quoted or expression.strip() == '/') and
                            ('/' in value or '\\' in value or re.match(r'^[A-Za-z]:', value))):
                        metadata_path(value)
    filesets = named(component, 's:fileSets/s:fileSet')
    # IP-XACT view references carry the HDL role; fileset names are arbitrary.
    hdl_groups = {}
    for view in named(component, 's:model/s:views/s:view').values():
        environment = text(view, 'envIdentifier')
        for role in ('synthesis', 'simulation'):
            language, separator, use = environment.partition(':vivado.xilinx.com:')
            if separator and use == role and language in ('', 'verilogSource', 'systemVerilogSource', 'vhdlSource'):
                refs = view.findall('s:fileSetRef/s:localName', N)
                require(role not in hdl_groups and len(refs) == 1,
                        f'Ambiguous {role} file group')
                group = (refs[0].text or '').strip()
                require(group in filesets, f'Missing {role} fileset: {group}')
                hdl_groups[role] = group
    require(set(hdl_groups) == {'synthesis', 'simulation'}, 'Missing synthesis/simulation views')
    require(len(set(hdl_groups.values())) == 2, 'Synthesis/simulation file groups must be distinct')
    all_files = []
    for group in filesets.values():
        entries = group.findall('s:file', N)
        seen = set()
        for entry in entries:
            name = text(entry, 'name')
            relative = PurePosixPath(name)
            require(name and not relative.is_absolute() and '..' not in relative.parts and
                    '\\' not in name and ':' not in name, f'Nonportable package path: {name}')
            file = root / name
            require(file.is_file() and file.resolve().is_relative_to(root), f'Missing or escaping package file: {name}')
            require(name not in seen, f'Duplicate fileset entry: {name}')
            seen.add(name)
            require(relative.name in expected or name == 'xgui/gpgpu_axi_v1_0.tcl', f'Nonproduction file: {name}')
            if relative.name in source_files:
                require(file.read_bytes() == source_files[relative.name].read_bytes(),
                        f'Packaged source differs from the current production input: {name}')
            if relative.name in source_files and relative.name not in header_names \
                    and relative.name != memory_name:
                source = file.read_text()
                uses = {}
                for m in re.finditer(r'`(\w+)', source):
                    if m.group(1) in header_macros:
                        uses.setdefault(header_macros[m.group(1)], m.start())
                for header_name, first_use in uses.items():
                    include = re.search(r'^\s*`include\s+"' + re.escape(header_name) + '"', source, re.M)
                    require(include is not None and include.start() < first_use,
                            f'Macro consumer needs explicit {header_name} before use: {name}')
                    header_path = file.with_name(header_name)
                    require(header_path.is_file() and header_path.resolve().is_relative_to(root) and
                            header_path.read_bytes() == source_files[header_name].read_bytes(),
                            f'{header_name} is not a portable sibling of: {name}')
            if relative.name == memory_name:
                require('mif' in [e.text for e in entry.findall('s:userFileType', N)], f'Wrong memory initialization type: {name}')
            else:
                kind = 'tclSource' if relative.suffix == '.tcl' else 'systemVerilogSource'
                require(text(entry, 'fileType') == kind, f'Wrong file type: {name}')
            all_files.append((name, entry))
        group_name = text(group, 'name')
        if group_name in hdl_groups.values():
            require({PurePosixPath(name).name for name in seen} == expected, f'Incomplete production fileset: {group_name}')
            ordered = [PurePosixPath(text(e, 'name')).name for e in entries]
            require(ordered == order, f'Production compile order differs: {group_name}')
            require(text(entries[-1], 'fileType') == 'systemVerilogSource' and
                    text(entries[-1], 'isIncludeFile') not in ('true', '1'),
                    f'Last fileset entry must be HDL: {group_name}')
            # The packager treats the last compile-order file as the top file.
            top = text(component, 'name')
            require(re.search(rf'^\s*module\s+{re.escape(top)}\b',
                              (root / text(entries[-1], 'name')).read_text(), re.M),
                    f'Last fileset entry must declare top module {top}: {group_name}')
            for header in (e for e in entries if PurePosixPath(text(e, 'name')).name in header_names):
                require(text(header, 'isIncludeFile') in ('true', '1'),
                        f'{text(header, "name")} is not an include in {group_name}')
    require('xilinx_xpgui_view_fileset' in filesets, 'Missing XGUI fileset')
    require(any(n == 'xgui/gpgpu_axi_v1_0.tcl' for n, _ in all_files), 'Missing XGUI')
    users = named(component, 's:parameters/s:parameter')
    models = named(component, 's:model/s:modelParameters/s:modelParameter')
    for param in ('SP_PER_SM','C_S00_AXI_DATA_WIDTH','C_S00_AXI_ADDR_WIDTH'):
        require(param in users and param in models, f'Missing HDL/user parameter: {param}')
        value = number(text(users[param], 'value'))
        require(value > 0 if param == 'SP_PER_SM' else value == 32, f'Invalid parameter: {param}')
        v = models[param].find('s:value', N)
        require(v is not None and f"PARAM_VALUE.{param}" in v.get(f'{{{NS}}}dependency', ''), f'Missing HDL mapping: {param}')
    gui = (root / 'xgui/gpgpu_axi_v1_0.tcl').read_text()
    require(gui == (FLOW / 'ip/xgui/gpgpu_axi_v1_0.tcl').read_text(), 'XGUI differs from production parameter mapping')
    for param in ('SP_PER_SM','C_S00_AXI_DATA_WIDTH','C_S00_AXI_ADDR_WIDTH'):
        require(f'proc update_MODELPARAM_VALUE.{param}' in gui and f'${{PARAM_VALUE.{param}}}' in gui and f'${{MODELPARAM_VALUE.{param}}}' in gui, f'Missing XGUI mapping: {param}')
    buses = named(component, 's:busInterfaces/s:busInterface')
    for name, kind, role, maps in [
        ('s00_axi','aximm','slave',{p: 's00_axi_'+p.lower() for p in AXI_PORTS}),
        ('s00_axi_aclk','clock','slave',{'CLK':'s00_axi_aclk'}),
        ('s00_axi_aresetn','reset','slave',{'RST':'s00_axi_aresetn'}),
        ('irq','interrupt','master',{'INTERRUPT':'irq'})]:
        require(name in buses, f'Missing interface: {name}')
        b = buses[name]; bt = b.find('s:busType', N)
        require(bt is not None and bt.get(f'{{{NS}}}name') == kind and bt.get(f'{{{NS}}}vendor') == 'xilinx.com', f'Wrong interface type: {name}')
        require(b.find('s:'+role,N) is not None, f'Wrong interface role: {name}')
        actual = {text(e.find('s:logicalPort',N),'name'): text(e.find('s:physicalPort',N),'name') for e in b.findall('s:portMaps/s:portMap',N)}
        require(actual == maps, f'Wrong port mapping: {name}')
    for name, values in {
        's00_axi': {'PROTOCOL':'AXI4LITE','DATA_WIDTH':'32','ADDR_WIDTH':'32'},
        's00_axi_aclk': {'ASSOCIATED_BUSIF':'s00_axi','ASSOCIATED_RESET':'s00_axi_aresetn'},
        's00_axi_aresetn': {'POLARITY':'ACTIVE_LOW'},
        'irq': {'SENSITIVITY':'LEVEL_HIGH'},
    }.items():
        actual = parameters(buses[name])
        require(all(actual.get(k) == v for k,v in values.items()), f'Wrong interface parameters: {name}')
    ref = buses['s00_axi'].find('s:slave/s:memoryMapRef',N)
    require(ref is not None and ref.get(f'{{{NS}}}memoryMapRef') == 's00_axi', 'Wrong memory map reference')
    maps = named(component,'s:memoryMaps/s:memoryMap')
    require('s00_axi' in maps, 'Missing s00_axi memory map')
    blocks = named(maps['s00_axi'],'s:addressBlock')
    require(set(blocks) == {'reg0'}, 'Wrong address blocks')
    block = blocks['reg0']
    require(number(text(block,'baseAddress')) == 0 and number(text(block,'range')) == 65536 and
            number(text(block,'width')) == 32 and text(block,'usage') == 'register', 'Wrong 64-KiB decoded aperture')
    range_node = block.find('s:range', N)
    require(not range_node.get(f'{{{NS}}}dependency'), 'Aperture must not depend on AXI address width')
