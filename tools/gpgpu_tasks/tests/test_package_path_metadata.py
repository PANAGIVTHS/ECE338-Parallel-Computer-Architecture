"""Semantic package path checks using the production packaging fixture."""
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


spec = importlib.util.spec_from_file_location(
    'package_path_fixture', Path(__file__).with_name('test_ip_packaging.py'))
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)
NS = fixture_module.load_package().NS
N = {'s': NS}
X = 'http://www.xilinx.com'


@pytest.fixture
def package(tmp_path):
    root = fixture_module.package_fixture(tmp_path)
    tree = ET.parse(root / 'component.xml')
    return root, tree


def validate(package):
    root, tree = package
    tree.write(root / 'component.xml')
    fixture_module.validate(root)


def extension(tree):
    return ET.SubElement(tree.getroot(), f'{{{NS}}}vendorExtensions')


def test_taxonomy_descriptions_and_identifiers_are_not_paths(package):
    _, tree = package
    vendor = extension(tree)
    taxonomies = ET.SubElement(vendor, f'{{{X}}}taxonomies')
    ET.SubElement(taxonomies, f'{{{X}}}taxonomy').text = '/UserIP'
    ET.SubElement(taxonomies, f'{{{X}}}taxonomy').text = '/Embedded/Compute'
    ET.SubElement(vendor, 'description').text = 'See /development/project/src and ../notes; C:\\docs is an example.'
    ET.SubElement(vendor, 'identifier', value='/identifier/not/a/file').text = '/ordinary/identifier'
    validate(package)


@pytest.mark.parametrize('field', ['includeDirs', 'includeDirectories', 'projectPath', 'guiPath', 'toolPath'])
@pytest.mark.parametrize('value', ['/external/project', 'C:/external/project', 'C:\\external\\project',
                                   '\\\\server\\share', '//server/share', '../outside', 'src/../../outside',
                                   'src\\..\\outside'])
def test_actual_metadata_paths_reject_external_and_traversal(package, field, value):
    _, tree = package
    ET.SubElement(extension(tree), field).text = value
    with pytest.raises(ValueError, match='[Pp]ath|[Dd]irectory'):
        validate(package)


@pytest.mark.parametrize('value', ['src', '.', 'src; xgui', '{src} {xgui}'])
def test_existing_relative_include_directories_pass(package, value):
    _, tree = package
    header = tree.find('s:fileSets/s:fileSet/s:file', N)
    ET.SubElement(header, f'{{{X}}}includeDirs').text = value
    validate(package)


@pytest.mark.parametrize('value', ['missing', 'src/constants.svh'])
def test_include_directory_must_exist_and_be_directory(package, value):
    _, tree = package
    ET.SubElement(extension(tree), 'includeDirs').text = value
    with pytest.raises(ValueError):
        validate(package)


def test_relative_include_symlink_cannot_escape(package):
    root, tree = package
    (root / 'escape').symlink_to(root.parent, target_is_directory=True)
    ET.SubElement(extension(tree), 'includeDirs').text = 'escape'
    with pytest.raises(ValueError):
        validate(package)


def test_metadata_path_attribute_is_checked(package):
    _, tree = package
    ET.SubElement(extension(tree), 'project', projectPath='/external/project')
    with pytest.raises(ValueError):
        validate(package)


@pytest.mark.parametrize('value', ['/external/src', 'C:/external/src', 'C:\\external\\src',
                                   '\\\\server\\share', '//server/share', '../outside',
                                   'src/../../outside', 'src\\..\\outside'])
@pytest.mark.parametrize('placement', ['element', 'attribute'])
def test_file_group_dependency_paths_are_checked(package, value, placement):
    _, tree = package
    group = tree.find('s:fileSets/s:fileSet', N)
    expression = f"file_exists('{value}')"
    if placement == 'element':
        ET.SubElement(group, f'{{{X}}}dependency').text = expression
    else:
        group.set(f'{{{X}}}dependency', expression)
    with pytest.raises(ValueError):
        validate(package)


@pytest.mark.parametrize('expression', ['', "spirit:decode(id('PARAM_VALUE.SP_PER_SM')) > 0",
                                        "file_exists('src/constants.svh')", '8 / 2 > 0'])
def test_nonpath_or_portable_file_group_dependency_passes(package, expression):
    _, tree = package
    group = tree.find('s:fileSets/s:fileSet', N)
    ET.SubElement(group, f'{{{X}}}dependency').text = expression
    validate(package)


@pytest.mark.parametrize('expression', ['/external/src', '/', "file_exists('/')", "file_exists('..')",
                                        "file_exists('escape')", "file_exists('escape/src')"])
def test_bare_and_symlink_dependency_paths_fail(package, expression):
    root, tree = package
    (root / 'escape').symlink_to(root.parent, target_is_directory=True)
    group = tree.find('s:fileSets/s:fileSet', N)
    ET.SubElement(group, 'dependency').text = expression
    with pytest.raises(ValueError):
        validate(package)


@pytest.mark.parametrize('placement', ['value_attribute', 'named_parameter'])
def test_metadata_path_value_encodings_fail(package, placement):
    _, tree = package
    vendor = extension(tree)
    if placement == 'value_attribute':
        ET.SubElement(vendor, 'toolPath', value='/external/tool')
    else:
        parameter = ET.SubElement(vendor, f'{{{NS}}}parameter')
        ET.SubElement(parameter, f'{{{NS}}}name').text = 'PROJECT_PATH'
        ET.SubElement(parameter, f'{{{NS}}}value').text = '/external/project'
    with pytest.raises(ValueError):
        validate(package)


@pytest.mark.parametrize('value', ['/external/header.svh', 'C:/external/header.svh',
                                   '\\\\server\\share\\header.svh', 'src/../../header.svh'])
def test_file_entries_remain_strict(package, value):
    _, tree = package
    tree.find('s:fileSets/s:fileSet/s:file/s:name', N).text = value
    with pytest.raises(ValueError):
        validate(package)
