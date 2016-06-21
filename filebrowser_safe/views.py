from __future__ import unicode_literals

from json import dumps
import os
import re
import datetime

from django.conf import settings as django_settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import default_storage
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.core.urlresolvers import reverse
from django.dispatch import Signal
from django import forms
from django.http import HttpResponseRedirect, HttpResponseBadRequest
from django.shortcuts import render_to_response, HttpResponse
from django.template import RequestContext as Context
from django.utils.translation import ugettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt

try:
    from django.utils.encoding import smart_text
except ImportError:
    # Backward compatibility for Py2 and Django < 1.5
    from django.utils.encoding import smart_unicode as smart_text

from filebrowser_safe.settings import *
from filebrowser_safe.functions import (get_path, get_breadcrumbs,
    get_file_type, get_filterdate, get_settings_var, get_directory,
    convert_filename)
from filebrowser_safe.templatetags.fb_tags import query_helper
from filebrowser_safe.base import FileObject
from filebrowser_safe.decorators import flash_login_required
from filebrowser_safe.models import FileBrowserItem

from mezzanine.utils.importing import import_dotted_path


# Add some required methods to FileSystemStorage
storage_class_name = django_settings.DEFAULT_FILE_STORAGE.split(".")[-1]
mixin_class_name = "filebrowser_safe.storage.%sMixin" % storage_class_name

# Workaround for django-s3-folder-storage
if django_settings.DEFAULT_FILE_STORAGE == 's3_folder_storage.s3.DefaultStorage':
    mixin_class_name = 'filebrowser_safe.storage.S3BotoStorageMixin'

try:
    mixin_class = import_dotted_path(mixin_class_name)
    storage_class = import_dotted_path(django_settings.DEFAULT_FILE_STORAGE)
except ImportError:
    pass
else:
    if mixin_class not in storage_class.__bases__:
        storage_class.__bases__ += (mixin_class,)


# Precompile regular expressions
filter_re = []
for exp in EXCLUDE:
    filter_re.append(re.compile(exp))
for k, v in VERSIONS.items():
    exp = (r'_%s.(%s)') % (k, '|'.join(EXTENSION_LIST))
    filter_re.append(re.compile(exp))


def remove_thumbnails(file_path):
    """
    Cleans up previous Mezzanine thumbnail directories when
    a new file is written (upload or rename).
    """
    from mezzanine.conf import settings
    dir_name, file_name = os.path.split(file_path)
    path = os.path.join(dir_name, settings.THUMBNAILS_DIR_NAME, file_name)
    try:
        default_storage.rmtree(path)
    except:
        pass


@xframe_options_sameorigin
def browse(request):
    """
    Browse Files/Directories.
    """

    # QUERY / PATH CHECK
    query = request.GET.copy()
    path_relative = query.get('dir', '')

    parent = None
    if path_relative:
        parent_query = FileBrowserItem.objects.filter(
            path_relative_directory=path_relative,
            filetype='folder')
        if not parent_query.exists():
            msg = _('The requested Folder does not exist.')
            messages.add_message(request, messages.ERROR, msg)
            redirect_url = reverse("fb_browse") + query_helper(query, "", "dir")
            return HttpResponseRedirect(redirect_url)

        else:
            parent = parent_query.first()

    files_query = FileBrowserItem.objects.filter(parent=parent)

    # INITIAL VARIABLES
    results_var = {
        'results_total': files_query.count(),
        'results_current': 0,
        'delete_total': 0,
        'images_total': files_query.filter(filetype='image').count(),
        'select_total': 0
    }
    counter = {}
    for k, v in EXTENSIONS.items():
        counter[k] = files_query.filter(filetype=k.lower()).count()

    files = []
    filter_date = request.GET.get('filter_date', '')

    if request.GET.get('q', None):
        files_query = files_query.filter(
            filename__icontains=request.GET.get('q').lower())

    filter_type = request.GET.get('filter_type', None)
    if filter_type:
        files_query = files_query.filter(filetype=filter_type.lower())

    if filter_date:
        today = datetime.date.today()
        if filter_date == 'today':
            files_query = files_query.filter(
                datetime=today)
        elif filter_date == 'thismonth':
            files_query = files_query.filter(
                datetime__year=today.year,
                datetime__month=today.month)
        elif filter_date == 'thisyear':
            files_query = files_query.filter(
                datetime__year=today.year)
        elif filter_date == 'past7days':
            week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
            files_query = files_query.filter(
                datetime__gte=week_ago)

    # SORTING
    query['o'] = request.GET.get('o', DEFAULT_SORTING_BY)
    query['ot'] = request.GET.get('ot', DEFAULT_SORTING_ORDER)
    if query['o'] == 'date':
        order_by = 'datetime'
    else:
        order_by = query['o']
    if not request.GET.get('ot') \
            and DEFAULT_SORTING_ORDER == "desc" \
            or request.GET.get('ot') == "desc":
        order_by = '-' + order_by

    files_query = files_query.order_by(order_by)
    files = list(files_query)

    results_var['results_current'] = files_query.count()

    if not query.get('type'):
        results_var['select_total'] = results_var['results_current']
    else:
        if query.get('type') in SELECT_FORMATS:
            filetypes = [t.lower() for t in SELECT_FORMATS[query.get('type')]]
            results_var['select_total'] = files_query.filter(
                filetype__in=filetypes)

    p = Paginator(files, LIST_PER_PAGE)
    try:
        page_nr = request.GET.get('p', '1')
    except:
        page_nr = 1
    try:
        page = p.page(page_nr)
    except (EmptyPage, InvalidPage):
        page = p.page(p.num_pages)
    return render_to_response('filebrowser/index.html', {
        'dir': path_relative,
        'p': p,
        'page': page,
        'results_var': results_var,
        'counter': counter,
        'query': query,
        'title': _(u'Media Library'),
        'settings_var': get_settings_var(),
        'breadcrumbs': get_breadcrumbs(query, path_relative),
        'breadcrumbs_title': ""
    }, context_instance=Context(request))
browse = staff_member_required(never_cache(browse))


# mkdir signals
filebrowser_pre_createdir = Signal(providing_args=["path", "dirname"])
filebrowser_post_createdir = Signal(providing_args=["path", "dirname"])


@xframe_options_sameorigin
def mkdir(request):
    """
    Make Directory.
    """

    from filebrowser_safe.forms import MakeDirForm

    # QUERY / PATH CHECK
    query = request.GET
    path_relative = query.get('dir', '')
    path = ''
    parent = None
    if path_relative:
        parent_query = FileBrowserItem.objects.filter(
            path_relative_directory=path_relative,
            filetype='folder')
        if not parent_query.exists():
            msg = _('The requested Folder does not exist.')
            messages.add_message(request, messages.ERROR, msg)
            return HttpResponseRedirect(reverse("fb_browse"))
        else:
            parent = parent_query.first()
            path = path_relative
    abs_path = os.path.join(get_directory(), path)

    if request.method == 'POST':
        form = MakeDirForm(abs_path, request.POST)
        if form.is_valid():
            server_path = os.path.join(abs_path, form.cleaned_data['dir_name'])
            try:
                # PRE CREATE SIGNAL
                filebrowser_pre_createdir.send(sender=request, path=path, dirname=form.cleaned_data['dir_name'])
                # CREATE FOLDER
                default_storage.makedirs(server_path)
                # POST CREATE SIGNAL
                filebrowser_post_createdir.send(sender=request, path=path, dirname=form.cleaned_data['dir_name'])

                fileobject = FileObject(server_path)
                FileBrowserItem.objects.create(
                    filename=fileobject.filename,
                    parent=parent,
                    path=fileobject.path,
                    path_relative_directory=fileobject.path_relative_directory,
                    url=fileobject.url,
                    extension=fileobject.extension,
                    filetype=fileobject.filetype.lower(),
                    filesize=fileobject.filesize,
                    datetime=fileobject.datetime
                )
                # MESSAGE & REDIRECT
                msg = _('The Folder %s was successfully created.') % (form.cleaned_data['dir_name'])
                messages.add_message(request, messages.SUCCESS, msg)
                # on redirect, sort by date desc to see the new directory on top of the list
                # remove filter in order to actually _see_ the new folder
                # remove pagination
                redirect_url = reverse("fb_browse") + query_helper(query, "ot=desc,o=date", "ot,o,filter_type,filter_date,q,p")
                return HttpResponseRedirect(redirect_url)
            except OSError as xxx_todo_changeme:
                (errno, strerror) = xxx_todo_changeme.args
                if errno == 13:
                    form.errors['dir_name'] = forms.utils.ErrorList([_('Permission denied.')])
                else:
                    form.errors['dir_name'] = forms.utils.ErrorList([_('Error creating folder.')])
    else:
        form = MakeDirForm(abs_path)

    return render_to_response('filebrowser/makedir.html', {
        'form': form,
        'query': query,
        'title': _(u'New Folder'),
        'settings_var': get_settings_var(),
        'breadcrumbs': get_breadcrumbs(query, path),
        'breadcrumbs_title': _(u'New Folder')
    }, context_instance=Context(request))
mkdir = staff_member_required(never_cache(mkdir))


@xframe_options_sameorigin
def upload(request):
    """
    Multiple File Upload.
    """

    from django.http import parse_cookie

    # QUERY / PATH CHECK
    query = request.GET
    path_relative = query.get('dir', '')
    path = ''
    parent = None
    if path_relative:
        parent_query = FileBrowserItem.objects.filter(
            path_relative_directory=path_relative,
            filetype='folder')
        if not parent_query.exists():
            msg = _('The requested Folder does not exist.')
            messages.add_message(request, messages.ERROR, msg)
            return HttpResponseRedirect(reverse("fb_browse"))
        else:
            path = path_relative

    # SESSION (used for flash-uploading)
    cookie_dict = parse_cookie(request.META.get('HTTP_COOKIE', ''))
    engine = __import__(settings.SESSION_ENGINE, {}, {}, [''])
    session_key = cookie_dict.get(settings.SESSION_COOKIE_NAME, None)

    return render_to_response('filebrowser/upload.html', {
        'query': query,
        'title': _(u'Select files to upload'),
        'settings_var': get_settings_var(),
        'session_key': session_key,
        'breadcrumbs': get_breadcrumbs(query, path),
        'breadcrumbs_title': _(u'Upload')
    }, context_instance=Context(request))
upload = staff_member_required(never_cache(upload))


@csrf_exempt
def _check_file(request):
    """
    Check if file already exists on the server.
    """
    folder = request.POST.get('folder')
    fb_uploadurl_re = re.compile(r'^.*(%s)' % reverse("fb_upload"))
    folder = fb_uploadurl_re.sub('', folder)
    fileArray = {}
    if request.method == 'POST':
        for k, v in list(request.POST.items()):
            if k != "folder":
                if default_storage.exists(os.path.join(get_directory(), folder, v)):
                    fileArray[k] = v
    return HttpResponse(dumps(fileArray))


# upload signals
filebrowser_pre_upload = Signal(providing_args=["path", "file"])
filebrowser_post_upload = Signal(providing_args=["path", "file"])


@csrf_exempt
@flash_login_required
@staff_member_required
def _upload_file(request):
    """
    Upload file to the server.

    Implement unicode handlers - https://github.com/sehmaschine/django-filebrowser/blob/master/filebrowser/sites.py#L471
    """
    if request.method == 'POST':
        folder = request.POST.get('folder')
        fb_uploadurl_re = re.compile(r'^.*(%s)' % reverse("fb_upload"))
        folder = fb_uploadurl_re.sub('', folder)
        if "." in folder:
            return HttpResponseBadRequest("")

        parent_path = folder if folder else None
        parent_query = FileBrowserItem.objects.filter(
            path_relative_directory=parent_path,
            filetype='folder')
        parent = parent_query.first()

        if request.FILES:
            filedata = request.FILES['Filedata']
            directory = get_directory()

            # Validate file against EXTENSIONS setting.
            if not get_file_type(filedata.name):
                return HttpResponseBadRequest("")

            # PRE UPLOAD SIGNAL
            filebrowser_pre_upload.send(sender=request, path=request.POST.get('folder'), file=filedata)

            # Try and remove both original and normalised thumb names,
            # in case files were added programmatically outside FB.
            file_path = os.path.join(directory, folder, filedata.name)
            remove_thumbnails(file_path)
            filedata.name = convert_filename(filedata.name)
            file_path = os.path.join(directory, folder, filedata.name)
            remove_thumbnails(file_path)

            # HANDLE UPLOAD
            uploadedfile = default_storage.save(file_path, filedata)
            if default_storage.exists(file_path) and file_path != uploadedfile:
                default_storage.move(smart_text(uploadedfile), smart_text(file_path), allow_overwrite=True)

            # POST UPLOAD SIGNAL
            filebrowser_post_upload.send(sender=request, path=request.POST.get('folder'), file=FileObject(smart_text(file_path)))

            if not FileBrowserItem.objects.filter(path=file_path).exists():
                fileobject = FileObject(file_path)
                FileBrowserItem.objects.create(
                    filename=fileobject.filename,
                    parent=parent,
                    path=fileobject.path,
                    path_relative_directory=fileobject.path_relative_directory,
                    url=fileobject.url,
                    extension=fileobject.extension,
                    filetype=fileobject.filetype.lower(),
                    filesize=fileobject.filesize,
                    datetime=fileobject.datetime
                )

        get_params = request.POST.get('get_params')
        if get_params:
            return HttpResponseRedirect(reverse('fb_browse') + get_params)
    return HttpResponse('True')


# delete signals
filebrowser_pre_delete = Signal(providing_args=["path", "filename"])
filebrowser_post_delete = Signal(providing_args=["path", "filename"])


@xframe_options_sameorigin
def delete(request):
    """
    Delete existing File/Directory.

    When trying to delete a Directory, the Directory has to be empty.
    """

    if request.method != "POST":
        return HttpResponseRedirect(reverse("fb_browse"))

    # QUERY / PATH CHECK
    query = request.GET
    path = get_path(query.get('dir', ''))
    filename = query.get('filename', '')
    if path is None or filename is None:
        if path is None:
            msg = _('The requested Folder does not exist.')
        else:
            msg = _('The requested File does not exist.')
        messages.add_message(request, messages.ERROR, msg)
        return HttpResponseRedirect(reverse("fb_browse"))
    abs_path = os.path.join(get_directory(), path)

    normalized = os.path.normpath(os.path.join(get_directory(), path, filename))

    if not normalized.startswith(get_directory()) or ".." in normalized:
        msg = _("An error occurred")
        messages.add_message(request, messages.ERROR, msg)
    elif request.GET.get('filetype') != "Folder":
        relative_server_path = os.path.join(get_directory(), path, filename)
        try:
            # PRE DELETE SIGNAL
            filebrowser_pre_delete.send(sender=request, path=path, filename=filename)
            # DELETE FILE
            default_storage.delete(os.path.join(abs_path, filename))
            # POST DELETE SIGNAL
            filebrowser_post_delete.send(sender=request, path=path, filename=filename)

            ### TODO REMOVE FILES IN FOLDER

            FileBrowserItem.objects.filter(path=normalized).delete()
            # MESSAGE & REDIRECT
            msg = _('The file %s was successfully deleted.') % (filename.lower())
            messages.add_message(request, messages.SUCCESS, msg)
        except OSError:
            msg = _("An error occurred")
            messages.add_message(request, messages.ERROR, msg)
    else:
        try:
            # PRE DELETE SIGNAL
            filebrowser_pre_delete.send(sender=request, path=path, filename=filename)
            # DELETE FOLDER
            default_storage.rmtree(os.path.join(abs_path, filename))
            # POST DELETE SIGNAL
            filebrowser_post_delete.send(sender=request, path=path, filename=filename)
            FileBrowserItem.objects.filter(path=normalized).delete()
            # MESSAGE & REDIRECT
            msg = _('The folder %s was successfully deleted.') % (filename.lower())
            messages.add_message(request, messages.SUCCESS, msg)
        except OSError:
            msg = _("An error occurred")
            messages.add_message(request, messages.ERROR, msg)
    qs = query_helper(query, "", "filename,filetype")
    return HttpResponseRedirect(reverse("fb_browse") + qs)
delete = staff_member_required(never_cache(delete))


# rename signals
filebrowser_pre_rename = Signal(providing_args=["path", "filename", "new_filename"])
filebrowser_post_rename = Signal(providing_args=["path", "filename", "new_filename"])


@xframe_options_sameorigin
def rename(request):
    """
    Rename existing File/Directory.

    Includes renaming existing Image Versions/Thumbnails.
    """

    from filebrowser_safe.forms import RenameForm

    # QUERY / PATH CHECK
    query = request.GET
    path = get_path(query.get('dir', ''))
    filename = query.get('filename', '')
    if path is None or filename is None:
        if path is None:
            msg = _('The requested Folder does not exist.')
        else:
            msg = _('The requested File does not exist.')
        messages.add_message(request, messages.ERROR, msg)
        return HttpResponseRedirect(reverse("fb_browse"))
    abs_path = os.path.join(MEDIA_ROOT, get_directory(), path)
    file_extension = os.path.splitext(filename)[1].lower()

    if request.method == 'POST':
        form = RenameForm(abs_path, file_extension, request.POST)
        if form.is_valid():
            relative_server_path = os.path.join(get_directory(), path, filename)
            new_filename = form.cleaned_data['name'] + file_extension
            new_relative_server_path = os.path.join(get_directory(), path, new_filename)
            try:
                # PRE RENAME SIGNAL
                filebrowser_pre_rename.send(sender=request, path=path, filename=filename, new_filename=new_filename)
                # RENAME ORIGINAL
                remove_thumbnails(new_relative_server_path)
                default_storage.move(relative_server_path, new_relative_server_path)
                # POST RENAME SIGNAL
                filebrowser_post_rename.send(sender=request, path=path, filename=filename, new_filename=new_filename)

                fileobject = FileObject(new_relative_server_path)
                FileBrowserItem.objects.filter(path=relative_server_path).update(
                    filename=fileobject.filename,
                    path=fileobject.path,
                    path_relative_directory=fileobject.path_relative_directory,
                    url=fileobject.url,
                )
                # MESSAGE & REDIRECT
                msg = _('Renaming was successful.')
                messages.add_message(request, messages.SUCCESS, msg)
                redirect_url = reverse("fb_browse") + query_helper(query, "", "filename")
                return HttpResponseRedirect(redirect_url)
            except OSError as xxx_todo_changeme1:
                (errno, strerror) = xxx_todo_changeme1.args
                form.errors['name'] = forms.util.ErrorList([_('Error.')])
    else:
        form = RenameForm(abs_path, file_extension)

    return render_to_response('filebrowser/rename.html', {
        'form': form,
        'query': query,
        'file_extension': file_extension,
        'title': _(u'Rename "%s"') % filename,
        'settings_var': get_settings_var(),
        'breadcrumbs': get_breadcrumbs(query, path),
        'breadcrumbs_title': _(u'Rename')
    }, context_instance=Context(request))
rename = staff_member_required(never_cache(rename))
