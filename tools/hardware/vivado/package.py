"""Fail-closed IP-XACT validation before publication of a staged Vivado IP.

No Vivado/Tcl runtime dependency and no writes. Invalid packages raise ValueError.
The synthesis/simulation filesets must contain the exact production manifest.
"""
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

NS = 'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'
N = {'s': NS}
FLOW = Path(__file__).resolve().parent
AXI_PORTS = 'AWADDR AWPROT AWVALID AWREADY WDATA WSTRB WVALID WREADY BRESP BVALID BREADY ARADDR ARPROT ARVALID ARREADY RDATA RRESP RVALID RREADY'.split()


def validate_package(path: str | Path) -> None:
    """Require portable production sources, VLNV and decoded 64-KiB ABI."""
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
    manifest_text = (FLOW / 'production_sources.tcl').read_text()
    match = re.search(r'set PRODUCTION_RTL_SOURCES\s*\{([^}]+)\}', manifest_text)
    require(match is not None, 'Invalid production manifest')
    source_files = {PurePosixPath(p).name: FLOW.parents[2] / 'hardware/rtl/gpgpu' / p
                    for p in match.group(1).split()}
    source_files['empty.mem'] = FLOW / 'ip/empty.mem'
    expected = set(source_files)
    # Metadata can hide include/GUI/tool paths outside fileset declarations.
    absolute = re.compile(r'(?:^|[\s=\";{])(?:/[^/\s]|[A-Za-z]:[\\/]|\.\./)')
    for element in component.iter():
        for value in [element.text or '', *element.attrib.values()]:
            require(not absolute.search(value), f'External path in component metadata: {value}')
    filesets = named(component, 's:fileSets/s:fileSet')
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
            if relative.name == 'empty.mem':
                require('mif' in [e.text for e in entry.findall('s:userFileType', N)], f'Wrong memory initialization type: {name}')
            else:
                kind = 'tclSource' if relative.suffix == '.tcl' else 'systemVerilogSource'
                require(text(entry, 'fileType') == kind, f'Wrong file type: {name}')
            all_files.append((name, entry))
        group_name = text(group, 'name')
        if group_name in ('xilinx_anylanguagesynthesis_view_fileset','xilinx_anylanguagebehavioralsimulation_view_fileset'):
            require({PurePosixPath(name).name for name in seen} == expected, f'Incomplete production fileset: {group_name}')
            ordered = [PurePosixPath(text(e, 'name')).name for e in entries]
            require(ordered[:2] == ['constants.svh', 'MemoryInterface.sv'], f'Interface/header compile order: {group_name}')
            header = next(e for e in entries if PurePosixPath(text(e,'name')).name == 'constants.svh')
            require(text(header,'isIncludeFile') in ('true','1'), f'constants.svh is not an include in {group_name}')
    for group in ('xilinx_anylanguagesynthesis_view_fileset','xilinx_anylanguagebehavioralsimulation_view_fileset','xilinx_xpgui_view_fileset'):
        require(group in filesets, f'Missing fileset: {group}')
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
