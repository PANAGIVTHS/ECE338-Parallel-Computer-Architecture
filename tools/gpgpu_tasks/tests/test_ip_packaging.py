"""Portable production IP packaging contracts; no Vivado/reference mutation."""
import importlib.util
import re
from pathlib import Path
import shutil
import subprocess
import pytest


def tcl_interpreter():
    # Tcl-only checks are optional; importing this module never requires Tk.
    try:
        import tkinter
    except ImportError as exc:
        pytest.skip(f'Tcl interpreter unavailable: {exc}')
    try:
        return tkinter.Tcl()
    except tkinter.TclError as exc:
        pytest.skip(f'Tcl interpreter unavailable: {exc}')


ROOT = Path(__file__).resolve().parents[3]
FLOW = ROOT / 'tools/hardware/vivado'


def load_package():
    spec = importlib.util.spec_from_file_location('ip_package', FLOW / 'package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def production_config():
    from config import resolve_config
    return resolve_config(ROOT)


def production_inputs():
    """(memory_init, sources, headers) resolved from hardware.sources and hardware.vivado."""
    from tools.hardware.vivado.tasks import production_inputs as resolve
    return resolve(production_config())


def input_names():
    memory, sources, _ = production_inputs()
    return [memory.name, *(p.name for p in sources)]


def validate(root):
    load_package().validate_package(root, *production_inputs())


def test_production_inputs_follow_configuration():
    config = production_config()
    memory, sources, headers = production_inputs()
    root = (ROOT / config.get('paths.rtl.sources.gpgpu')).resolve()
    excluded = set(config.get('hardware.vivado.exclude_sources'))
    ordered = [root / rel for rel in config.get('hardware.sources.ordered')
               if not excluded & set(Path(rel).parts)]
    assert memory == (ROOT / config.get('hardware.vivado.memory_init')).resolve()
    # Headers lead, then the shared compile order minus Vivado's exclusions.
    assert headers and sources[:len(headers)] == headers
    assert sources[len(headers):len(headers) + len(ordered)] == ordered
    assert not any(excluded & set(p.relative_to(root).parts) for p in sources)
    assert all(p.suffix in config.get('hardware.sources.header_extensions') for p in headers)
    assert all(p.suffix in config.get('hardware.sources.extensions') for p in sources[len(headers):])
    # ipx::package_project takes the last compile-order file as the IP top file.
    from tools.hardware.vivado.tasks import IP_TOP
    declares = [p for p in sources if re.search(rf'^\s*module\s+{IP_TOP}\b', p.read_text(), re.M)]
    assert declares == [sources[-1]]
    # Every resolved input passes the Tcl-side check Vivado runs.
    tcl = tcl_interpreter()
    tcl.eval(f'source {{{FLOW / "production_sources.tcl"}}}')
    paths = tcl.splitlist(tcl.call('production_source_paths', str(memory),
                                   tuple(map(str, sources)), tuple(map(str, headers))))
    assert [Path(str(p)).name for p in paths] == input_names()


def test_production_source_check_rejects_missing_and_colliding_inputs(tmp_path):
    memory, sources, headers = production_inputs()
    tcl = tcl_interpreter()
    tcl.eval(f'source {{{FLOW / "production_sources.tcl"}}}')
    import tkinter
    for rtl, header in [((*map(str, sources), str(tmp_path / 'absent.sv')), ()),
                        ((*map(str, sources), str(sources[-1])), ()),
                        (tuple(map(str, sources)), (str(tmp_path / 'stray.svh'),))]:
        with pytest.raises(tkinter.TclError):
            tcl.call('production_source_paths', str(memory), rtl, header)


def package_fixture(tmp_path):
    """Representative IP-XACT, not a fabricated Vivado build result."""
    import xml.etree.ElementTree as ET
    ns = 'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'
    def add(parent, tag, text=None, **attrs):
        e = ET.SubElement(parent, '{' + ns + '}' + tag,
                          {'{' + ns + '}' + k: v for k, v in attrs.items()})
        e.text = text
        return e
    r = ET.Element('{' + ns + '}component')
    for tag, value in [('vendor','user.org'), ('library','user'), ('name','gpgpu_axi'), ('version','1.0')]:
        add(r,tag,value)
    buses = add(r,'busInterfaces')
    for name, kind, role, params in [
        ('s00_axi','aximm','slave',{'PROTOCOL':'AXI4LITE','DATA_WIDTH':'32','ADDR_WIDTH':'32'}),
        ('s00_axi_aclk','clock','slave',{'ASSOCIATED_BUSIF':'s00_axi','ASSOCIATED_RESET':'s00_axi_aresetn'}),
        ('s00_axi_aresetn','reset','slave',{'POLARITY':'ACTIVE_LOW'}),
        ('irq','interrupt','master',{'SENSITIVITY':'LEVEL_HIGH'})]:
        b=add(buses,'busInterface'); add(b,'name',name)
        add(b,'busType',vendor='xilinx.com',library='interface' if kind=='aximm' else 'signal',name=kind,version='1.0')
        role_node=add(b,role)
        if name=='s00_axi': add(role_node,'memoryMapRef',memoryMapRef='s00_axi')
        maps=add(b,'portMaps')
        logicals = ['AWADDR','AWPROT','AWVALID','AWREADY','WDATA','WSTRB','WVALID','WREADY','BRESP','BVALID','BREADY','ARADDR','ARPROT','ARVALID','ARREADY','RDATA','RRESP','RVALID','RREADY'] if kind=='aximm' else [{'clock':'CLK','reset':'RST','interrupt':'INTERRUPT'}[kind]]
        for logical in logicals:
            m=add(maps,'portMap'); add(add(m,'logicalPort'),'name',logical)
            add(add(m,'physicalPort'),'name', 's00_axi_'+logical.lower() if kind=='aximm' else name)
        p=add(b,'parameters')
        for key,value in params.items():
            item=add(p,'parameter'); add(item,'name',key); add(item,'value',value)
    mm=add(add(r,'memoryMaps'),'memoryMap'); add(mm,'name','s00_axi')
    block=add(mm,'addressBlock')
    for tag,value in [('name','reg0'),('baseAddress','0'),('range','65536'),('width','32'),('usage','register')]: add(block,tag,value)
    model=add(r,'model'); mp=add(model,'modelParameters'); up=add(r,'parameters')
    for name,value in [('SP_PER_SM','8'),('C_S00_AXI_DATA_WIDTH','32'),('C_S00_AXI_ADDR_WIDTH','32')]:
        p=add(up,'parameter');add(p,'name',name);add(p,'value',value,resolve='user')
        p=add(mp,'modelParameter');add(p,'name',name);add(p,'value',value,resolve='generated',dependency=f"spirit:decode(id('PARAM_VALUE.{name}'))")
    files=add(r,'fileSets')
    memory_init, sources, headers = production_inputs()
    for index, group in enumerate(['xilinx_anylanguagesynthesis_view_fileset','xilinx_anylanguagebehavioralsimulation_view_fileset']):
        view = add(add(model, 'views') if index == 0 else model.find('{'+ns+'}views'), 'view')
        add(view, 'name', 'synthesis' if index == 0 else 'simulation')
        add(view, 'envIdentifier', ':vivado.xilinx.com:' + ('synthesis' if index == 0 else 'simulation'))
        add(add(view, 'fileSetRef'), 'localName', group)
        fs=add(files,'fileSet');add(fs,'name',group)
        for src in [memory_init, *sources]:
            dest=tmp_path/'src'/src.name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(src,dest)
            f=add(fs,'file');add(f,'name','src/'+dest.name)
            if src!=memory_init: add(f,'fileType','systemVerilogSource')
            else: add(f,'userFileType','mif')
            if src in headers:add(f,'isIncludeFile','true')
    fs=add(files,'fileSet');add(fs,'name','xilinx_xpgui_view_fileset');f=add(fs,'file');add(f,'name','xgui/gpgpu_axi_v1_0.tcl');add(f,'fileType','tclSource')
    xgui=tmp_path/'xgui/gpgpu_axi_v1_0.tcl';xgui.parent.mkdir();shutil.copyfile(FLOW/'ip/xgui/gpgpu_axi_v1_0.tcl',xgui)
    ET.ElementTree(r).write(tmp_path/'component.xml')
    return tmp_path


def test_validate_portable_production_package(tmp_path):
    assert (FLOW/'package.py').exists(), 'package validator missing'
    assert (FLOW/'ip/xgui/gpgpu_axi_v1_0.tcl').exists(), 'parameter XGUI missing'
    assert validate(package_fixture(tmp_path)) is None


@pytest.mark.parametrize('mutation', [
    'missing_memory','missing_source','absolute_path','traversal','external_symlink',
    'extra_source','header_not_include','header_type','memory_type','interface_order','memory_last','top_not_last',
    'range_4gb','range_dependency','wrong_clock','wrong_reset','edge_irq',
    'wrong_bus_map','wrong_protocol','wrong_vlnv','missing_hdl_mapping',
    'wrong_xgui_mapping','missing_gui','invalid_xml','external_metadata','external_include','external_memory', 'header_not_sibling',
])
def test_package_validation_fails_closed(tmp_path, mutation):
    import xml.etree.ElementTree as ET
    root=package_fixture(tmp_path)
    xml=root/'component.xml';tree=ET.parse(xml);r=tree.getroot()
    ns={'s':'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'}
    q=lambda tag: '{'+ns['s']+'}'+tag
    def value(name):
        return next(p.find('s:value',ns) for p in r.findall('.//s:parameter',ns) if p.findtext('s:name',namespaces=ns)==name)
    files=r.findall('s:fileSets/s:fileSet',ns)
    first=files[0].find('s:file',ns)
    header=next(f for f in files[0].findall('s:file',ns) if f.findtext('s:name',namespaces=ns).endswith('constants.svh'))
    if mutation == 'header_not_sibling':
        # Any source that includes a production header must keep it as a sibling.
        _, sources, headers = production_inputs()
        consumer = next(p.name for p in sources if p not in headers and any(
            f'`include "{h.name}"' in p.read_text() for h in headers))
        (root / 'nested').mkdir()
        shutil.copyfile(root / 'src' / consumer, root / 'nested' / consumer)
        entry = next(f for f in files[0].findall('s:file', ns)
                     if f.findtext('s:name', namespaces=ns).endswith(consumer))
        entry.find('s:name', ns).text = 'nested/' + consumer
    elif mutation=='missing_memory': (root/'src/empty.mem').unlink()
    elif mutation=='missing_source': (root/'src/AXI4LiteTop.v').unlink()
    elif mutation=='external_metadata':
        extension=ET.SubElement(r,q('vendorExtensions'));ET.SubElement(extension,'projectPath').text='/external/project'
    elif mutation=='external_include':
        ET.SubElement(header,'includeDirs').text='/external/include'
    elif mutation=='external_memory':
        memory=root/'src/GPGPU.sv'
        memory.write_text(memory.read_text().replace('empty.mem','/external/empty.mem'))
    elif mutation=='absolute_path': first.find('s:name',ns).text=str(root/'src/constants.svh')
    elif mutation=='traversal': first.find('s:name',ns).text='../constants.svh'
    elif mutation=='external_symlink':
        f=root/'src/constants.svh';f.unlink();f.symlink_to(ROOT/'hardware/rtl/gpgpu/constants.svh')
    elif mutation=='extra_source':
        f=ET.SubElement(files[0],q('file'));ET.SubElement(f,q('name')).text='src/board.xdc';(root/'src/board.xdc').write_text('')
    elif mutation=='header_not_include': header.find('s:isIncludeFile',ns).text='false'
    elif mutation=='header_type': header.find('s:fileType',ns).text='verilogSource'
    elif mutation=='memory_type':
        next(f for f in files[0].findall('s:file',ns) if f.findtext('s:name',namespaces=ns).endswith('empty.mem')).find('s:userFileType',ns).text='systemVerilogSource'
    elif mutation=='memory_last':
        memory = next(f for f in files[0].findall('s:file',ns) if f.findtext('s:name',namespaces=ns).endswith('empty.mem'))
        files[0].remove(memory); files[0].append(memory)
    elif mutation=='top_not_last':
        for group in files[:2]:
            entries=group.findall('s:file',ns);top=entries[-1];group.remove(top);group.insert(list(group).index(entries[1]),top)
    elif mutation=='interface_order':
        interface=next(f for f in files[0].findall('s:file',ns) if f.findtext('s:name',namespaces=ns).endswith('MemoryInterface.sv'));files[0].remove(interface);files[0].append(interface)
    elif mutation=='range_4gb': r.find('s:memoryMaps/s:memoryMap/s:addressBlock/s:range',ns).text='0x100000000'
    elif mutation=='range_dependency': r.find('s:memoryMaps/s:memoryMap/s:addressBlock/s:range',ns).set(q('dependency'),'pow(2,32)')
    elif mutation=='wrong_clock': value('ASSOCIATED_BUSIF').text='other'
    elif mutation=='wrong_reset': value('POLARITY').text='ACTIVE_HIGH'
    elif mutation=='edge_irq': value('SENSITIVITY').text='EDGE_RISING'
    elif mutation=='wrong_bus_map': r.find('.//s:physicalPort/s:name',ns).text='wrong'
    elif mutation=='wrong_protocol': value('PROTOCOL').text='AXI4'
    elif mutation=='wrong_vlnv': r.find('s:version',ns).text='2.0'
    elif mutation=='missing_hdl_mapping': r.find('s:model/s:modelParameters/s:modelParameter/s:value',ns).attrib.clear()
    elif mutation=='wrong_xgui_mapping':
        gui=root/'xgui/gpgpu_axi_v1_0.tcl';gui.write_text(gui.read_text().replace('set_property value [get_property value ${PARAM_VALUE.SP_PER_SM}]','set_property value 32 ;# ${PARAM_VALUE.SP_PER_SM}'))
    elif mutation=='missing_gui': (root/'xgui/gpgpu_axi_v1_0.tcl').unlink()
    elif mutation == 'invalid_xml': pass
    else: raise AssertionError(f'Unknown fixture mutation: {mutation}')
    if mutation=='invalid_xml': xml.write_text('<invalid')
    else: tree.write(xml)
    with pytest.raises(ValueError): validate(root)


@pytest.mark.parametrize('language', ['', 'verilogSource', 'systemVerilogSource', 'vhdlSource'])
def test_validator_resolves_vendor_views_not_fileset_names(tmp_path, language):
    import xml.etree.ElementTree as ET
    root = package_fixture(tmp_path)
    xml = root / 'component.xml'
    tree = ET.parse(xml)
    ns = {'s': 'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'}
    groups = tree.findall('s:fileSets/s:fileSet', ns)
    views = tree.findall('s:model/s:views/s:view', ns)
    for index, view in enumerate(views):
        name = f'actual_vendor_group_{index}'
        groups[index].find('s:name', ns).text = name
        view.find('s:fileSetRef/s:localName', ns).text = name
        environment = view.find('s:envIdentifier', ns)
        environment.text = language + environment.text
    tree.write(xml)
    validate(root)


@pytest.mark.parametrize('mutation', ['missing_view', 'dangling_ref', 'duplicate_role', 'incomplete_simulation', 'absolute_dependency'])
def test_validator_rejects_invalid_semantic_filesets(tmp_path, mutation):
    import xml.etree.ElementTree as ET
    root = package_fixture(tmp_path)
    xml = root / 'component.xml'
    tree = ET.parse(xml)
    ns = {'s': 'http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009'}
    views = tree.find('s:model/s:views', ns)
    view = list(views)[1]
    if mutation == 'missing_view':
        views.remove(view)
    elif mutation == 'dangling_ref':
        view.find('s:fileSetRef/s:localName', ns).text = 'absent'
    elif mutation == 'duplicate_role':
        view.find('s:envIdentifier', ns).text = ':vivado.xilinx.com:synthesis'
    elif mutation == 'incomplete_simulation':
        group = tree.findall('s:fileSets/s:fileSet', ns)[1]
        group.remove(group.findall('s:file', ns)[-1])
    elif mutation == 'absolute_dependency':
        group = tree.findall('s:fileSets/s:fileSet', ns)[0]
        ET.SubElement(group, '{'+ns['s']+'}vendorExtensions').set('dependency', '/development/project/src')
    else:
        raise AssertionError(mutation)
    tree.write(xml)
    with pytest.raises(ValueError):
        validate(root)


def tcl_driver(tmp_path, script, *, group_types=None, **overrides):
    """Execute real drivers with a Tcl command recorder, not a vendor build."""
    flow = tmp_path/'flow';flow.mkdir(exist_ok=True)
    for name in ('production_sources.tcl', script): shutil.copyfile(FLOW/name,flow/name)
    from tools.hardware.vivado.tasks import write_source_manifest
    manifest = tmp_path / 'sources.tsv'
    write_source_manifest(manifest, production_inputs())
    shutil.copytree(FLOW/'ip',flow/'ip',dirs_exist_ok=True)
    project=tmp_path/'project'; staging=tmp_path/'staging'
    values={'PROJECT_DIR':project,'PROJECT_NAME':'gpgpu_ip_dev','PROJECT_FILE':project/'gpgpu_ip_dev.xpr',
            'TOP_NAME':'gpgpu_axi','FPGA_PART':'xc7z020clg484-1','NUM_CORES':8,'IP_REVISION':7,'FLOW_VERSION':'2025.2',
            'REPO_ROOT':ROOT,'SOURCES_MANIFEST':manifest,'IP_REPO_DIR':staging}
    values.update(overrides)
    (flow/'common.tcl').write_text('\n'.join(f'set {k} {{{v}}}' for k,v in values.items()))
    tcl=tcl_interpreter(); commands=[]
    import tkinter
    groups = dict(group_types if group_types is not None else {
        'vendor_synth_group': 'synthesis',
        'vendor_sim_group': 'simulation',
    })
    def record(name,*args):
        commands.append((name,args))
        if name == 'ipx::get_file_groups':
            # A guessed group NAME does not select these real typed objects.
            return tuple(groups) if args == ('-of_objects', 'object') else ''
        if name == 'ipx::add_file_group':
            assert args[0] == '-type' and len(args) == 4
            groups[args[2]] = ('synthesis' if args[1] == 'xilinx_anylanguagesynthesis' else 'simulation')
            return args[2]
        if name == 'get_property' and args[0] == 'type':
            return groups[args[1]]
        if name == 'ipx::get_files':
            return 'imported_absolute_file'
        if name == 'get_property' and args == ('name', 'imported_absolute_file'):
            return '/development/project/src/imported.sv'
        if name=='version':return '2025.2'
        if name=='get_property' and args[0]=='NAME':return 'default'
        if name.startswith('get_') or name.startswith('ipx::get_'):return args[-1] if args else 'object'
        return 'object'
    tcl.createcommand('record',record)
    tcl.eval('namespace eval ipx {}; proc unknown {name args} {return [record $name {*}$args]}')
    error=None
    try:tcl.eval(f'source {{{flow/script}}}')
    except tkinter.TclError as exc:error=str(exc)
    return commands,error,values


def test_ip_project_recreation_is_portable_production_only(tmp_path):
    assert (FLOW/'create_ip_project.tcl').is_file(), 'IP project entry point missing'
    calls,error,values=tcl_driver(tmp_path,'create_ip_project.tcl')
    assert error is None
    assert any(name=='create_project' and '-force' not in args for name,args in calls)
    added=[args[-1] for name,args in calls if name=='add_files']
    assert added
    assert sorted(p.name for p in (values['PROJECT_DIR']/'src').iterdir())==sorted(input_names())
    assert not any(name in ('open_project','launch_runs','read_xdc') for name,args in calls)
    assert any(name=='set_property' and args[:2]==('generic','SP_PER_SM=8') for name,args in calls)


@pytest.mark.parametrize('guard', ['existing_project','wrong_version','wrong_top'])
def test_ip_project_preflight_never_overwrites_reference(tmp_path,guard):
    kwargs={}
    if guard=='existing_project':
        project=tmp_path/'project';project.mkdir();(project/'gpgpu_ip_dev.xpr').write_text('precious')
    elif guard=='wrong_version':kwargs['FLOW_VERSION']='2024.2'
    else:kwargs['TOP_NAME']='GPGPU'
    calls,error,_=tcl_driver(tmp_path,'create_ip_project.tcl',**kwargs)
    assert error
    assert not any(name=='create_project' for name,args in calls)


@pytest.mark.parametrize('group_types,created,ambiguous', [
    (None, 0, False),
    ({}, 2, False),
    ({'actual_synthesis': 'synthesis'}, 1, False),
    ({'verilog_synth': 'synthesis',
      'verilog_sim': 'simulation'}, 0, False),
    ({'synth_one': 'synthesis',
      'synth_two': 'synthesis'}, 0, True),
])
def test_ip_package_driver_configures_contract_without_reference_opens(tmp_path, group_types, created, ambiguous):
    assert (FLOW/'package_ip.tcl').is_file(), 'IP packaging entry point missing'
    project=tmp_path/'project';project.mkdir();(project/'gpgpu_ip_dev.xpr').write_text('disposable test project')
    (project/'.production-ip-project').write_text('gpgpu_axi production project v1\n')
    (project/'src').mkdir()
    memory_init, sources, _ = production_inputs()
    for p in [memory_init, *sources]:
        shutil.copyfile(p, project/'src'/p.name)
    calls,error,values=tcl_driver(tmp_path,'package_ip.tcl', group_types=group_types)
    if ambiguous:
        assert 'Ambiguous packaged synthesis file groups' in error
        assert not any(n == 'ipx::check_integrity' for n, _ in calls)
        return
    assert error is None
    assert sum(n == 'ipx::add_file_group' for n, _ in calls) == created
    for group in {a[-1] for n, a in calls if n == 'ipx::add_file'}:
        ordered = [Path(a[0]).name for n, a in calls if n == 'ipx::add_file' and a[-1] == group]
        assert ordered == input_names()
    package_index = next(i for i, (n, _) in enumerate(calls) if n == 'ipx::package_project')
    before = calls[:package_index]
    assert any(n == 'set_property' and a[:2] == ('is_global_include', 'false') for n, a in before)
    assert sum(n == 'set_property' and a[:2] == ('include_dirs', '') for n, a in before) == 2
    assert sum(n == 'set_property' and a[:2] == ('dependency', '') for n, a in calls) == 2
    assert sum(n == 'set_property' and a[:2] == ('model_name', 'gpgpu_axi') for n, a in calls) == 2
    assert sum(n == 'ipx::remove_file' and a[0] == '/development/project/src/imported.sv' for n, a in calls) == 2
    assert not any(n == 'ipx::get_file_groups' and a[0] != '-of_objects' for n, a in calls)
    assert ('open_project',(str(values['PROJECT_FILE']),)) in calls
    assert any(n=='ipx::package_project' and '-import_files' in a for n,a in calls)
    assert any(n=='set_property' and a[:2]==('range','65536') for n,a in calls)
    assert any(n=='set_property' and a[:2]==('value','LEVEL_HIGH') for n,a in calls)
    assert any(n=='set_property' and a[:2]==('value','AXI4LITE') for n,a in calls)
    assert any(n=='ipx::check_integrity' for n,a in calls)
    assert (values['IP_REPO_DIR']/'xgui/gpgpu_axi_v1_0.tcl').read_bytes()==(FLOW/'ip/xgui/gpgpu_axi_v1_0.tcl').read_bytes()


def test_package_refuses_populated_destination_before_open(tmp_path):
    staging=tmp_path/'staging';staging.mkdir();(staging/'component.xml').write_text('precious')
    calls,error,_=tcl_driver(tmp_path,'package_ip.tcl')
    assert error
    assert not any(n=='open_project' for n,a in calls)
    assert (staging/'component.xml').read_text()=='precious'


@pytest.mark.parametrize('value,expected', [
    ('24', 'true'), ('0', 'false'), ('-1', 'false'),
    ('not-an-integer', 'false'), ('1.5', 'false'), ('', 'false'),
])
def test_sp_per_sm_xgui_returns_literal_booleans(value, expected):
    """Execute production Tcl; this does not substitute for vendor customization."""
    tcl = tcl_interpreter()
    calls = []
    def get_property(*args):
        calls.append(args)
        return value
    tcl.createcommand('get_property', get_property)
    tcl.call('source', str(FLOW / 'ip/xgui/gpgpu_axi_v1_0.tcl'))
    assert tcl.eval('validate_PARAM_VALUE.SP_PER_SM test_parameter') == expected
    assert calls == [('value', 'test_parameter')]


def test_sp_per_sm_xgui_preserves_property_errors():
    tcl = tcl_interpreter()
    import tkinter
    tcl.eval('proc get_property {args} {error "property lookup failed"}')
    tcl.call('source', str(FLOW / 'ip/xgui/gpgpu_axi_v1_0.tcl'))
    with pytest.raises(tkinter.TclError, match='property lookup failed'):
        tcl.call('validate_PARAM_VALUE.SP_PER_SM', 'test_parameter')
