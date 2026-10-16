"""Portable production IP packaging contracts; no Vivado/reference mutation."""
import importlib.util
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


def test_manifest_is_explicit_production_and_required_inputs_exist():
    assert (FLOW / 'production_sources.tcl').is_file(), 'production manifest is missing'
    tcl = tcl_interpreter()
    tcl.eval(f'source {{{FLOW / "production_sources.tcl"}}}')
    paths = tuple(map(str, tcl.splitlist(tcl.call('production_source_paths', str(ROOT / 'hardware/rtl/gpgpu'), str(FLOW)))))
    assert Path(paths[0]).name == 'constants.svh'
    assert Path(paths[1]).name == 'MemoryInterface.sv'
    assert Path(paths[-1]).name == 'empty.mem'
    assert all(Path(p).is_file() for p in paths)
    assert not any('experimental' in p or '/tb/' in p or 'HostControllerProcessor' in p or p.endswith('.xdc') for p in paths)
    assert len(paths) == len(set(paths)) == 20
    assert (FLOW / 'ip/empty.mem').read_text().splitlines() == ['00000000'] * 2048


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
    manifest = FLOW.joinpath('production_sources.tcl').read_text().split('set PRODUCTION_RTL_SOURCES {')[1].split('}')[0].split()
    for group in ['xilinx_anylanguagesynthesis_view_fileset','xilinx_anylanguagebehavioralsimulation_view_fileset']:
        fs=add(files,'fileSet');add(fs,'name',group)
        for relative in manifest + ['empty.mem']:
            src=FLOW/'ip/empty.mem' if relative=='empty.mem' else ROOT/'hardware/rtl/gpgpu'/relative
            dest=tmp_path/'src'/Path(relative).name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(src,dest)
            f=add(fs,'file');add(f,'name','src/'+dest.name)
            if relative!='empty.mem': add(f,'fileType','systemVerilogSource')
            else: add(f,'userFileType','mif')
            if relative=='constants.svh':add(f,'isIncludeFile','true')
    fs=add(files,'fileSet');add(fs,'name','xilinx_xpgui_view_fileset');f=add(fs,'file');add(f,'name','xgui/gpgpu_axi_v1_0.tcl');add(f,'fileType','tclSource')
    xgui=tmp_path/'xgui/gpgpu_axi_v1_0.tcl';xgui.parent.mkdir();shutil.copyfile(FLOW/'ip/xgui/gpgpu_axi_v1_0.tcl',xgui)
    ET.ElementTree(r).write(tmp_path/'component.xml')
    return tmp_path


def test_validate_portable_production_package(tmp_path):
    assert (FLOW/'package.py').exists(), 'package validator missing'
    assert (FLOW/'ip/xgui/gpgpu_axi_v1_0.tcl').exists(), 'parameter XGUI missing'
    package = load_package()
    assert package.validate_package(package_fixture(tmp_path)) is None


@pytest.mark.parametrize('mutation', [
    'missing_memory','missing_source','absolute_path','traversal','external_symlink',
    'extra_source','header_not_include','header_type','memory_type','interface_order',
    'range_4gb','range_dependency','wrong_clock','wrong_reset','edge_irq',
    'wrong_bus_map','wrong_protocol','wrong_vlnv','missing_hdl_mapping',
    'wrong_xgui_mapping','missing_gui','invalid_xml','external_metadata','external_include','external_memory',
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
    header=first
    if mutation=='missing_memory': (root/'src/empty.mem').unlink()
    elif mutation=='missing_source': (root/'src/AXI4LiteTop.sv').unlink()
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
    elif mutation=='interface_order':
        interface=files[0].findall('s:file',ns)[1];files[0].remove(interface);files[0].append(interface)
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
    if mutation=='invalid_xml': xml.write_text('<invalid')
    else: tree.write(xml)
    with pytest.raises(ValueError): load_package().validate_package(root)


def tcl_driver(tmp_path, script, **overrides):
    """Execute real drivers with a Tcl command recorder, not a vendor build."""
    flow = tmp_path/'flow';flow.mkdir(exist_ok=True)
    for name in ('production_sources.tcl', script): shutil.copyfile(FLOW/name,flow/name)
    shutil.copytree(FLOW/'ip',flow/'ip',dirs_exist_ok=True)
    project=tmp_path/'project'; staging=tmp_path/'staging'
    values={'PROJECT_DIR':project,'PROJECT_NAME':'gpgpu_ip_dev','PROJECT_FILE':project/'gpgpu_ip_dev.xpr',
            'TOP_NAME':'gpgpu_axi','FPGA_PART':'xc7z020clg484-1','NUM_CORES':8,'IP_REVISION':7,'FLOW_VERSION':'2025.2',
            'REPO_ROOT':ROOT,'RTL_DIR':ROOT/'hardware/rtl/gpgpu','IP_REPO_DIR':staging}
    values.update(overrides)
    (flow/'common.tcl').write_text('\n'.join(f'set {k} {{{v}}}' for k,v in values.items()))
    tcl=tcl_interpreter(); commands=[]
    import tkinter
    def record(name,*args):
        commands.append((name,args))
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
    assert len(list((values['PROJECT_DIR']/'src').iterdir()))==20
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


def test_ip_package_driver_configures_contract_without_reference_opens(tmp_path):
    assert (FLOW/'package_ip.tcl').is_file(), 'IP packaging entry point missing'
    project=tmp_path/'project';project.mkdir();(project/'gpgpu_ip_dev.xpr').write_text('disposable test project')
    (project/'.production-ip-project').write_text('gpgpu_axi production project v1\n')
    (project/'src').mkdir()
    tcl=tcl_interpreter();tcl.eval(f'source {{{FLOW/"production_sources.tcl"}}}')
    for p in tcl.splitlist(tcl.call('production_source_paths',str(ROOT/'hardware/rtl/gpgpu'),str(FLOW))):
        shutil.copyfile(str(p),project/'src'/Path(str(p)).name)
    calls,error,values=tcl_driver(tmp_path,'package_ip.tcl')
    assert error is None
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
